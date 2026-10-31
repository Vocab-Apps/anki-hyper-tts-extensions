# documentation:
# https://github.com/Vocab-Apps/anki-hyper-tts-extensions/blob/main/docs/services/YANDEX_TRANSLATE.md
#
# Text-to-speech through the same uniproxy gateway used by the "listen" button in
# Yandex Translate. The protocol is a private WebSocket API (no key, no documented SLA);
# this service reimplements it with the standard library so it runs inside Anki without
# aiohttp/websockets.
#
# protocol:
#   connect  wss://uniproxy.alice.yandex.net/uni.ws
#   send     {"event": {"header": {"namespace": "TTS", "name": "Generate", ...},
#                       "payload": {"text": ..., "lang": ..., "voice": ...,
#                                   "format": "audio/mp3" | "audio/ogg;codecs=opus",
#                                   "speed": 1.5 (optional)}}}
#   receive  {"directive": {"header": {"name": "Speak", "streamId": N}, ...}}
#   receive  binary frames: 4-byte big-endian streamId + audio payload
#   receive  {"streamcontrol": {"streamId": N, "reason": 0, "action": 0}}
#
# SynchronizeState is not required on this endpoint; sending Generate directly works and
# avoids tying a reused connection to the language of the first request.

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import uuid

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

# before Python 3.10, socket timeouts raise socket.timeout rather than the built-in TimeoutError
_TIMEOUT_ERRORS = (socket.timeout, TimeoutError)

WS_HOST = 'uniproxy.alice.yandex.net'
WS_PATH = '/uni.ws'
ORIGIN = 'https://translate.yandex.ru'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')

FORMAT_MP3 = 'audio/mp3'
FORMAT_OGG_OPUS = 'audio/ogg;codecs=opus'
# HyperTTS names (options.AudioFormat) -> what the gateway expects in TTS.Generate
GATEWAY_FORMATS = {
    options.AudioFormat.mp3.name: FORMAT_MP3,
    options.AudioFormat.ogg_opus.name: FORMAT_OGG_OPUS,
}

CONNECT_TIMEOUT = 20.0
SPEAK_TIMEOUT = 20.0
AUDIO_TIMEOUT = 60.0
# the gateway drops idle WebSockets somewhere between 70s and 90s; stay well below that
IDLE_RECONNECT_SECONDS = 55.0

# the gateway answered a single 15,000 character request in about a minute; keep a generous
# ceiling so a runaway field cannot tie up the addon for an unbounded amount of time
MAX_TEXT_CHARS = 20000
# 16 MiB is far above any single Opus page the gateway sends; protects against a bad length header
MAX_FRAME_BYTES = 16 * 1024 * 1024

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class _TransportError(Exception):
    """socket level failure: the connection can no longer be used"""


class _HandshakeError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail[:500]
        super().__init__(f'HTTP {status}: {self.detail}')


class _ServerError(Exception):
    def __init__(self, message, permanent=True):
        self.permanent = permanent
        super().__init__(message)


# ---------------------------------------------------------------------------
# minimal RFC 6455 client
# ---------------------------------------------------------------------------

class _WebSocketConnection:

    def __init__(self, connect_timeout=CONNECT_TIMEOUT):
        self._buffer = bytearray()
        self._sock = None
        self._seq = 0
        self._connect(connect_timeout)

    # -- connection setup ---------------------------------------------------

    def _connect(self, connect_timeout):
        try:
            sock = socket.create_connection((WS_HOST, 443), timeout=connect_timeout)
        except _TIMEOUT_ERRORS as e:
            raise _TransportError(f'timed out connecting to {WS_HOST}') from e
        except OSError as e:
            raise _TransportError(f'could not connect to {WS_HOST}: {e}') from e

        try:
            self._sock = self._wrap_tls(sock)
        except _TIMEOUT_ERRORS as e:
            sock.close()
            raise _TransportError(f'TLS handshake with {WS_HOST} timed out') from e
        except (ssl.SSLError, OSError) as e:
            sock.close()
            raise _TransportError(f'TLS handshake with {WS_HOST} failed: {e}') from e

        deadline = time.monotonic() + connect_timeout
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = (
            f'GET {WS_PATH} HTTP/1.1\r\n'
            f'Host: {WS_HOST}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            f'Origin: {ORIGIN}\r\n'
            f'User-Agent: {USER_AGENT}\r\n'
            '\r\n'
        )
        try:
            self._sock.sendall(request.encode('ascii'))
            status, detail = self._read_http_upgrade(deadline)
        except _TIMEOUT_ERRORS as e:
            self.close()
            raise _TransportError('timed out during the WebSocket handshake') from e
        except Exception:
            self.close()
            raise

        if status != 101:
            self.close()
            raise _HandshakeError(status, detail)

    def _wrap_tls(self, sock):
        context = ssl.create_default_context()
        try:
            # Anki/HyperTTS ship certifi; keep using it when available so certificate
            # handling matches what requests does elsewhere in the addon.
            import certifi
            context.load_verify_locations(cafile=certifi.where())
        except Exception:
            pass
        return context.wrap_socket(sock, server_hostname=WS_HOST)

    def _read_http_upgrade(self, deadline):
        while b'\r\n\r\n' not in self._buffer:
            self._recv_some(deadline)
        head, _, rest = bytes(self._buffer).partition(b'\r\n\r\n')
        self._buffer = bytearray(rest)
        status_line = head.split(b'\r\n', 1)[0].decode('latin-1')
        parts = status_line.split(' ', 2)
        if len(parts) < 2 or not parts[1].isdigit():
            raise _TransportError(f'unexpected WebSocket response: {status_line!r}')
        return int(parts[1]), head.decode('latin-1', 'replace')

    # -- frame I/O ----------------------------------------------------------

    def _recv_some(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('WebSocket receive timed out')
        self._sock.settimeout(remaining)
        try:
            data = self._sock.recv(65536)
        except _TIMEOUT_ERRORS:
            raise
        except OSError as e:
            raise _TransportError(f'WebSocket receive failed: {e}') from e
        if not data:
            raise _TransportError('the server closed the connection')
        self._buffer.extend(data)

    def _recv_exact(self, count, deadline):
        while len(self._buffer) < count:
            self._recv_some(deadline)
        data = bytes(self._buffer[:count])
        del self._buffer[:count]
        return data

    def _read_frame(self, deadline):
        first, second = self._recv_exact(2, deadline)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack('!H', self._recv_exact(2, deadline))[0]
        elif length == 127:
            length = struct.unpack('!Q', self._recv_exact(8, deadline))[0]
        if length > MAX_FRAME_BYTES:
            raise _TransportError(f'WebSocket frame too large: {length} bytes')
        mask = self._recv_exact(4, deadline) if masked else None
        payload = self._recv_exact(length, deadline) if length else b''
        if mask:
            payload = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _send_frame(self, opcode, payload):
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack('!H', length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack('!Q', length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index & 3] for index, byte in enumerate(payload))
        try:
            self._sock.settimeout(SPEAK_TIMEOUT)
            self._sock.sendall(bytes(header) + masked)
        except _TIMEOUT_ERRORS as e:
            raise _TransportError('timed out sending to the WebSocket') from e
        except OSError as e:
            raise _TransportError(f'WebSocket send failed: {e}') from e

    def send_text(self, text):
        self._send_frame(OPCODE_TEXT, text.encode('utf-8'))

    def send_json(self, message):
        self.send_text(json.dumps(message, ensure_ascii=False))

    def next_seq(self):
        self._seq += 1
        return self._seq

    def recv_message(self, deadline):
        """return (opcode, payload) for the next complete data message"""
        fragment_opcode = None
        fragment = bytearray()
        while True:
            fin, opcode, payload = self._read_frame(deadline)
            if opcode == OPCODE_PING:
                self._send_frame(OPCODE_PONG, payload)
                continue
            if opcode == OPCODE_PONG:
                continue
            if opcode == OPCODE_CLOSE:
                try:
                    self._send_frame(OPCODE_CLOSE, payload[:2])
                except Exception:
                    pass
                raise _TransportError('the server closed the WebSocket connection')
            if opcode in (OPCODE_TEXT, OPCODE_BINARY):
                if fin:
                    return opcode, payload
                fragment_opcode = opcode
                fragment = bytearray(payload)
                continue
            if opcode == OPCODE_CONTINUATION:
                if fragment_opcode is None:
                    raise _TransportError('unexpected WebSocket continuation frame')
                fragment.extend(payload)
                if fin:
                    complete_opcode = fragment_opcode
                    fragment_opcode = None
                    return complete_opcode, bytes(fragment)
                continue
            # unknown data/control opcode: ignore it and keep reading

    def close(self):
        sock = self._sock
        self._sock = None
        if sock is None:
            return
        try:
            sock.settimeout(2.0)
            header = bytearray([0x80 | OPCODE_CLOSE, 0x80 | 2])
            mask = os.urandom(4)
            header.extend(mask)
            header.extend(bytes(byte ^ mask[index & 3] for index, byte in enumerate(struct.pack('!H', 1000))))
            sock.sendall(bytes(header))
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# text handling
# ---------------------------------------------------------------------------

def _has_speakable_text(text):
    return any(char.isalnum() for char in text)


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------

# (display name, gateway lang, AudioLanguage, gender, gateway voice)
VOICE_DEFINITIONS = [
    ('Oksana', 'ru', languages.AudioLanguage.ru_RU, constants.Gender.Female, 'oksana.gpu'),
    ('Jane', 'ru', languages.AudioLanguage.ru_RU, constants.Gender.Female, 'jane.gpu'),
    ('David', 'en', languages.AudioLanguage.en_US, constants.Gender.Male, 'david.gpu'),
    ('Selay', 'tr', languages.AudioLanguage.tr_TR, constants.Gender.Female, 'selay.gpu'),
    ('Rezeda', 'tt', languages.AudioLanguage.tt_RU, constants.Gender.Female, 'rezeda.gpu'),
    ('Bashkir', 'ba', languages.AudioLanguage.ba_RU, constants.Gender.Any, 'bashkir.gpu'),
]


def _build_voice_options():
    return {
        'speed': {
            'type': 'number',
            'min': 0.5,
            'max': 3.0,
            'default': 1.0,
        },
        'format': {
            'type': 'list',
            'values': [options.AudioFormat.mp3.name, options.AudioFormat.ogg_opus.name],
            'default': options.AudioFormat.mp3.name,
        },
    }


class YandexTranslate(service.ServiceBase):

    def __init__(self):
        service.ServiceBase.__init__(self)
        # one WebSocket at a time: requests are serialized, and an idle connection is
        # dropped before the gateway closes it under us
        self._lock = threading.Lock()
        self._connection = None
        self._connection_last_used = 0.0

    @property
    def service_type(self) -> constants.ServiceType:
        return constants.ServiceType.tts

    @property
    def service_fee(self) -> constants.ServiceFee:
        return constants.ServiceFee.free

    def enabled_by_default(self):
        return True

    def cloudlanguagetools_enabled(self):
        return False

    def voice_list(self):
        voices = []
        for name, lang, audio_language, gender, gateway_voice in VOICE_DEFINITIONS:
            voices.append(voice.TtsVoice_v3(
                name=name,
                gender=gender,
                audio_languages=[audio_language],
                service=self.name,
                voice_key={'lang': lang, 'voice': gateway_voice},
                options=_build_voice_options(),
                service_fee=self.service_fee,
            ))
        return voices

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options):
        text = (source_text or '').strip()
        if not text:
            raise errors.ServiceInputError(source_text, voice, 'source text is empty')
        if not _has_speakable_text(text):
            raise errors.ServiceInputError(source_text, voice, 'source text has no speakable characters')
        if len(text) > MAX_TEXT_CHARS:
            raise errors.ServiceInputError(
                source_text, voice,
                f'text is too long ({len(text)} characters, the limit is {MAX_TEXT_CHARS}); '
                f'split the field or shorten the source text')

        lang = voice.voice_key['lang']
        voice_name = voice.voice_key['voice']

        format_name = voice_options.get(
            options.AUDIO_FORMAT_PARAMETER,
            voice.options.get(options.AUDIO_FORMAT_PARAMETER, {}).get('default', options.AudioFormat.mp3.name))
        gateway_format = GATEWAY_FORMATS.get(format_name)
        if gateway_format is None:
            raise errors.ServiceInputError(
                source_text, voice, f'unsupported audio format: {format_name}')

        speed = voice_options.get('speed', voice.options.get('speed', {}).get('default', 1.0))
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = 1.0
        speed = min(max(speed, 0.5), 3.0)
        if speed == 1.0:
            speed = None  # keep the payload identical to what Yandex Translate sends

        logger.info(f'YandexTranslate request: lang={lang} voice={voice_name} '
                    f'format={gateway_format} speed={speed} chars={len(text)}')

        with self._lock:
            audio = self._synthesize(source_text, voice, text, lang, voice_name, speed, gateway_format)

        if not audio:
            raise errors.UnknownServiceError(source_text, voice, 'Yandex returned no audio')
        return audio

    # -- request pipeline ---------------------------------------------------

    def _synthesize(self, source_text, voice, text, lang, voice_name, speed, gateway_format):
        last_error = None
        for attempt in range(2):
            try:
                connection = self._get_connection()
                audio = self._generate(
                    connection, source_text, voice, text, lang, voice_name, speed, gateway_format)
                self._connection_last_used = time.monotonic()
                return audio
            except _TIMEOUT_ERRORS as e:
                self._drop_connection()
                raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
            except _TransportError as e:
                self._drop_connection()
                last_error = e
                if attempt == 0:
                    logger.warning(f'YandexTranslate connection failed, retrying once: {e}')
                    continue
                raise errors.ServiceConnectionError(source_text, voice, str(e)) from e
            except _HandshakeError as e:
                self._drop_connection()
                if e.status in (401, 403):
                    raise errors.ServicePermissionError(
                        source_text, voice, f'gateway rejected the request: {e}') from e
                if e.status == 429:
                    raise errors.RateLimitRetryAfterError(source_text, voice, str(e), 30) from e
                if 500 <= e.status < 600:
                    raise errors.ServiceGatewayError(source_text, voice, str(e)) from e
                raise errors.UnknownServiceError(source_text, voice, str(e)) from e
            except _ServerError as e:
                self._drop_connection()
                if e.permanent:
                    raise errors.PermanentError(source_text, voice, str(e)) from e
                raise errors.UnknownServiceError(source_text, voice, str(e)) from e
        raise errors.ServiceConnectionError(source_text, voice, str(last_error))

    def _get_connection(self):
        now = time.monotonic()
        if self._connection is not None and now - self._connection_last_used <= IDLE_RECONNECT_SECONDS:
            return self._connection
        self._drop_connection()
        self._connection = _WebSocketConnection()
        self._connection_last_used = time.monotonic()
        return self._connection

    def _drop_connection(self):
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def _generate(self, connection, source_text, voice, text, lang, voice_name, speed, gateway_format):
        payload = {
            'text': text,
            'lang': lang,
            'voice': voice_name,
            'format': gateway_format,
        }
        if speed is not None:
            payload['speed'] = speed
        request = {
            'event': {
                'header': {
                    'namespace': 'TTS',
                    'name': 'Generate',
                    'messageId': str(uuid.uuid4()),
                    'seqNumber': connection.next_seq(),
                },
                'payload': payload,
            }
        }

        connection.send_json(request)
        speak_deadline = time.monotonic() + SPEAK_TIMEOUT
        audio_deadline = None
        stream_id = None
        audio = bytearray()

        while True:
            deadline = audio_deadline if audio_deadline is not None else speak_deadline
            try:
                opcode, message = connection.recv_message(deadline)
            except _TIMEOUT_ERRORS as e:
                if audio_deadline is None:
                    raise _ServerError(
                        f'Yandex did not start a speech stream for voice {voice_name!r} '
                        f'(the voice may no longer be available)') from e
                self._drop_connection()
                raise errors.ServiceTimeoutError(
                    source_text, voice, 'timed out while receiving audio') from e

            if opcode == OPCODE_TEXT:
                try:
                    parsed = json.loads(message.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                directive = parsed.get('directive')
                if directive:
                    header = directive.get('header') or {}
                    if header.get('name') == 'Speak':
                        stream_id = int(header.get('streamId', -1))
                        body = directive.get('payload') or {}
                        audio_deadline = time.monotonic() + AUDIO_TIMEOUT
                        logger.debug(f'YandexTranslate Speak: stream={stream_id} '
                                     f'format={body.get("format")} from_cache={body.get("from_cache")}')
                    elif 'Error' in str(header.get('name')):
                        body = directive.get('payload') or {}
                        raise _ServerError(f'Yandex gateway error: {json.dumps(body, ensure_ascii=False)}')

                control = parsed.get('streamcontrol')
                if control is not None:
                    control_stream = control.get('streamId')
                    if stream_id is not None and control_stream is not None and int(control_stream) != stream_id:
                        # a control frame for another stream; keep waiting for ours
                        continue
                    if int(control.get('action', 0)) != 0 or int(control.get('reason', 0)) != 0:
                        raise _ServerError(f'Yandex stream error: {control}')
                    break
                continue

            if opcode == OPCODE_BINARY:
                if len(message) <= 4:
                    continue
                frame_stream = int.from_bytes(message[:4], 'big')
                if stream_id is not None and frame_stream != stream_id:
                    # not the stream we asked for; ignore it and wait for ours
                    continue
                audio.extend(message[4:])
                audio_deadline = time.monotonic() + AUDIO_TIMEOUT
                continue

        if not audio:
            raise _ServerError('Yandex finished the stream without sending audio', permanent=False)
        return bytes(audio)

