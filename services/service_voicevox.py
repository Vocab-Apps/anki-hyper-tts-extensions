# documentation:
# https://github.com/Vocab-Apps/anki-hyper-tts-extensions/blob/main/docs/services/VOICEVOX.md
# contributed by @snorthman


import pathlib
import tempfile
import requests
import aqt.sound

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import options
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)


class VOICEVOX(service.ServiceBase):
    def __init__(self):
        service.ServiceBase.__init__(self)
        self._speakers: list[Speaker] = []
        self._voices: list[voice.TtsVoice_v3] = [
            voice.TtsVoice_v3(
                name='VOICEVOX not running!',
                gender=constants.Gender.Any,
                audio_languages=[languages.AudioLanguage.ja_JP],
                service=self.name,
                service_fee=self.service_fee,
                voice_key={'speaker': -1},
                options={}
            ),
        ]

    @property
    def service_type(self) -> constants.ServiceType:
        return constants.ServiceType.tts

    @property
    def service_fee(self) -> constants.ServiceFee:
        return constants.ServiceFee.free

    def voice_list(self):
        try:
            if len(self._voices) == 1:
                speakers = self._request('', '', requests.get, 'speakers')
                self._speakers = {_['speaker_uuid']: Speaker(self, _) for _ in speakers.json()}
                self._voices = [_.voice for _ in self._speakers.values()]
        except errors.ServiceRequestError:
            return self._voices  # we assume the container isn't running
        except Exception as e:
            logger.error(e)
            raise
        else:
            return self._voices

    def _request(self, source_text, voice, func, endpoint: str, **kwargs) -> requests.Response:
        try:
            response = func(f'http://127.0.0.1:50021/{endpoint}', **kwargs)
        except requests.exceptions.Timeout as e:
            raise errors.ServiceTimeoutError(source_text, voice, str(e)) from e
        except requests.exceptions.ConnectionError as e:
            raise errors.ServiceConnectionError(source_text, voice, str(e)) from e

        if response.status_code in (401, 403):
            raise errors.ServicePermissionError(source_text, voice, f'auth failed: {response.text}')
        if response.status_code != 200:
            raise errors.UnknownServiceError(source_text, voice, f'HTTP {response.status_code}: {response.text}')

        return response

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options) -> bytes:
        try:
            speaker_uuid = voice.voice_key['speaker_uuid']
            speaker = self._speakers[speaker_uuid]

            options = speaker.defaults | voice_options
            style_id = speaker.get_style_id(options.pop('style'))
            preset = {
                'id': 0,
                'name': 'hyper-tts',
                'speaker_uuid': speaker_uuid,
                'style_id': style_id,
                'pauseLength': 0,
                'pauseLengthScale': 1,
                **options
            }

            svp = source_text, voice, requests.post
            self._request(*svp, 'update_preset', json=preset, timeout=5)
            query = self._request(*svp, 'audio_query_from_preset', params={'text': source_text, 'preset_id': 0}, timeout=30).json()
            if query == {'detail': 'Internal Server Error'}:
                raise errors.ServiceInputError(source_text, voice, 'Internal Server Error')

            audio = self._request(*svp, 'synthesis', params={'speaker': style_id}, json=query, timeout=30).content

            with tempfile.TemporaryDirectory(prefix='hypertts_voicevox_') as tmpdir:
                wav_path = pathlib.Path(tmpdir) / 'audio.wav'
                mp3_path = pathlib.Path(tmpdir) / 'audio.mp3'

                wav_path.write_bytes(audio)
                aqt.sound._encode_mp3(str(wav_path), str(mp3_path))

                return mp3_path.read_bytes()
        except Exception as e:
            logger.error(e)
            raise


class Speaker:
    def __init__(self, service: VOICEVOX, speaker: dict):
        self._styles = {style_dict.get(style['name'], style['name']): style['id'] for style in speaker['styles']}
        options = {
            'style': dict(type='list', values=list(self._styles.keys()), default=next(iter(self._styles))),
            'speedScale': dict(type='number', min=0.5, max=2., default=1.),
            'pitchScale': dict(type='number', min=-0.15, max=0.15, default=0.),
            'intonationScale': dict(type='number', min=0., max=2., default=1.),
            'volumeScale': dict(type='number', min=0., max=1., default=1.),
            'prePhonemeLength': dict(type='number', min=0., max=1., default=0.2),
            'postPhonemeLength': dict(type='number', min=0., max=1., default=0.3),
        }
        self.defaults = {k: v['default'] for k, v in options.items()}

        name, gender = speaker_dict.get(speaker['name'], (speaker['name'], constants.Gender.Any))
        self.voice = voice.TtsVoice_v3(
            name=name,
            gender=gender,
            audio_languages=[languages.AudioLanguage.ja_JP],
            service=service.name,
            service_fee=service.service_fee,
            voice_key=dict(speaker_uuid=speaker['speaker_uuid']),
            options=options
        )

    def get_style_id(self, style):
        return self._styles[style]


style_dict = {
    '第二形態': 'transformed',
    'よわよわ': 'weak',
    'びくびく': 'jittery',
    'ぶりっ子': 'cutesy',
    '覚醒': 'awakened',
    '喜び': 'cheerful',
    '内緒話': 'whisper',
    'おちつき': 'calm',
    'セクシー／あん子': 'sexy',
    'びえーん': 'wailing',
    '呆れ': 'exasperated',
    '熱血': 'passionate',
    'わーい': 'cheerful',
    '恐怖': 'terrified',
    'あまあま': 'sweet',
    'ノーマル': 'normal',
    '人間ver.': 'human form',
    '鬼ver.': 'demon form',
    '元気': 'energetic',
    '怒り': 'angry',
    '人見知り': 'shy',
    '低血圧': 'sleepy',
    'ボーイ': 'boyish',
    'つよつよ': 'confident',
    'セクシー': 'sexy',
    'おどろき': 'surprised',
    'アナウンス': 'announcer',
    'ロリ': 'childlike',
    '悲しみ': 'sad',
    'ふつう': 'normal',
    'かなしい': 'sad',
    'かなしみ': 'sad',
    'ツクモちゃん': 'Tsukumo style',
    'クイーン': 'commanding',
    'こわがり': 'fearful',
    '読み聞かせ': 'storytelling',
    'つぼみ': 'Tsubomi style',
    'おこ': 'annoyed',
    'おどおど': 'nervous',
    'しっとり': 'mellow',
    '囁き': 'whisper',
    'うきうき': 'cheerful',
    'ささやき': 'whisper',
    '泣き': 'crying',
    'へろへろ': 'exhausted',
    'ヘロヘロ': 'exhausted',
    '哀しみ': 'sad',
    'のんびり': 'relaxed',
    'たのしい': 'cheerful',
    'ぬいぐるみver.': 'plushie form',
    'けだるげ': 'languid',
    '実況風': 'commentary',
    'ツンギレ': 'snappy',
    '人間（怒り）ver.': 'angry form',
    '甘々': 'sweet',
    'ツンツン': 'aloof',
    '絶望と敗北': 'defeated',
    'シリアス': 'serious',
    '明るい': 'cheerful',
    '不機嫌': 'grumpy',
    '楽々': 'easygoing',
    'ヒソヒソ': 'whisper',
    'なみだめ': 'teary',
}

speaker_dict = {
    '中部つるぎ': ('Chubu Tsurugi', constants.Gender.Female),
    '四国めたん': ('Shikoku Metan', constants.Gender.Female),
    'WhiteCUL': ('WhiteCUL', constants.Gender.Female),
    '猫使ビィ': ('Nekotsukai Bii', constants.Gender.Female),
    '栗田まろん': ('Kurita Maron', constants.Gender.Male),
    '櫻歌ミコ': ('Ouka Miko', constants.Gender.Female),
    '剣崎雌雄': ('Kenzaki Shiyuu', constants.Gender.Male),
    '離途': ('Rito', constants.Gender.Male),
    '冥鳴ひまり': ('Meimei Himari', constants.Gender.Female),
    '玄野武宏': ('Kurono Takehiro', constants.Gender.Male),
    '黒沢冴白': ('Kurosawa Saehaku', constants.Gender.Male),
    '琴詠ニア': ('Kotoyomi Nia', constants.Gender.Female),
    'ユーレイちゃん': ('Yuurei-chan (Ghost-chan)', constants.Gender.Female),
    '東北きりたん': ('Tohoku Kiritan', constants.Gender.Female),
    '里石ユカ': ('Satoishi Yuka', constants.Gender.Female),
    '白上虎太郎': ('Shirakami Kotaro', constants.Gender.Male),
    'あいえるたん': ('Aieru-tan', constants.Gender.Female),
    '後鬼': ('Goki', constants.Gender.Female),
    '雨晴はう': ('Amehare Hau', constants.Gender.Female),
    '猫使アル': ('Nekotsukai Aru', constants.Gender.Female),
    'ちび式じい': ('Chibi-shiki Jii', constants.Gender.Male),
    '雀松朱司': ('Wakamatsu Akashi', constants.Gender.Male),
    '青山龍星': ('Aoyama Ryusei', constants.Gender.Male),
    'Voidoll': ('Voidoll', constants.Gender.Any),
    'あんこもん': ('Ankomon', constants.Gender.Female),
    'No.7': ('No.7', constants.Gender.Female),
    '中国うさぎ': ('Chugoku Usagi', constants.Gender.Female),
    '波音リツ': ('Namine Ritsu', constants.Gender.Female),
    'ナースロボ＿タイプＴ': ('Nurse Robo Type-T', constants.Gender.Female),
    '春日部つむぎ': ('Kasukabe Tsumugi', constants.Gender.Female),
    'ぞん子': ('Zonko', constants.Gender.Female),
    '†聖騎士 紅桜†': ('Holy Knight Benizakura', constants.Gender.Male),
    '暁記ミタマ': ('Akeki Mitama', constants.Gender.Female),
    'ずんだもん': ('Zundamon', constants.Gender.Female),
    '九州そら': ('Kyushu Sora', constants.Gender.Female),
    '東北ずん子': ('Tohoku Zunko', constants.Gender.Female),
    '満別花丸': ('Manbetsu Hanamaru', constants.Gender.Female),
    '春歌ナナ': ('Haruka Nana', constants.Gender.Female),
    '東北イタコ': ('Tohoku Itako', constants.Gender.Female),
    '麒ヶ島宗麟': ('Kigashima Sorin', constants.Gender.Male),
    'もち子さん': ('Mochiko-san', constants.Gender.Female),
    '小夜/SAYO': ('Sayo', constants.Gender.Female),
    '夜語トバリ': ('Yogatari Tobari', constants.Gender.Female),
}
