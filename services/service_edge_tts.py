
# documentation:
# https://github.com/Vocab-Apps/anki-hyper-tts-extensions/blob/main/docs/services/EDGE_TTS.md
# contributed by @BEST8OY


import os
import subprocess
import tempfile

from hypertts_addon import voice
from hypertts_addon import service
from hypertts_addon import errors
from hypertts_addon import constants
from hypertts_addon import languages
from hypertts_addon import logging_utils

logger = logging_utils.get_child_logger(__name__)

LOCALE_TO_AUDIO_LANGUAGE = {
    'af-ZA': languages.AudioLanguage.af_ZA,
    'am-ET': languages.AudioLanguage.am_ET,
    'ar-AE': languages.AudioLanguage.ar_AE,
    'ar-BH': languages.AudioLanguage.ar_BH,
    'ar-DZ': languages.AudioLanguage.ar_DZ,
    'ar-EG': languages.AudioLanguage.ar_EG,
    'ar-IQ': languages.AudioLanguage.ar_IQ,
    'ar-JO': languages.AudioLanguage.ar_JO,
    'ar-KW': languages.AudioLanguage.ar_KW,
    'ar-LB': languages.AudioLanguage.ar_LB,
    'ar-LY': languages.AudioLanguage.ar_LY,
    'ar-MA': languages.AudioLanguage.ar_MA,
    'ar-OM': languages.AudioLanguage.ar_OM,
    'ar-QA': languages.AudioLanguage.ar_QA,
    'ar-SA': languages.AudioLanguage.ar_SA,
    'ar-SY': languages.AudioLanguage.ar_SY,
    'ar-TN': languages.AudioLanguage.ar_TN,
    'ar-YE': languages.AudioLanguage.ar_YE,
    'az-AZ': languages.AudioLanguage.az_AZ,
    'bg-BG': languages.AudioLanguage.bg_BG,
    'bn-BD': languages.AudioLanguage.bn_BD,
    'bn-IN': languages.AudioLanguage.bn_IN,
    'bs-BA': languages.AudioLanguage.bs_BA,
    'ca-ES': languages.AudioLanguage.ca_ES,
    'cs-CZ': languages.AudioLanguage.cs_CZ,
    'cy-GB': languages.AudioLanguage.cy_GB,
    'da-DK': languages.AudioLanguage.da_DK,
    'de-AT': languages.AudioLanguage.de_AT,
    'de-CH': languages.AudioLanguage.de_CH,
    'de-DE': languages.AudioLanguage.de_DE,
    'el-GR': languages.AudioLanguage.el_GR,
    'en-AU': languages.AudioLanguage.en_AU,
    'en-CA': languages.AudioLanguage.en_CA,
    'en-GB': languages.AudioLanguage.en_GB,
    'en-HK': languages.AudioLanguage.en_HK,
    'en-IE': languages.AudioLanguage.en_IE,
    'en-IN': languages.AudioLanguage.en_IN,
    'en-KE': languages.AudioLanguage.en_KE,
    'en-NG': languages.AudioLanguage.en_NG,
    'en-NZ': languages.AudioLanguage.en_NZ,
    'en-PH': languages.AudioLanguage.en_PH,
    'en-SG': languages.AudioLanguage.en_SG,
    'en-TZ': languages.AudioLanguage.en_TZ,
    'en-US': languages.AudioLanguage.en_US,
    'en-ZA': languages.AudioLanguage.en_ZA,
    'es-AR': languages.AudioLanguage.es_AR,
    'es-BO': languages.AudioLanguage.es_BO,
    'es-CL': languages.AudioLanguage.es_CL,
    'es-CO': languages.AudioLanguage.es_CO,
    'es-CR': languages.AudioLanguage.es_CR,
    'es-CU': languages.AudioLanguage.es_CU,
    'es-DO': languages.AudioLanguage.es_DO,
    'es-EC': languages.AudioLanguage.es_EC,
    'es-ES': languages.AudioLanguage.es_ES,
    'es-GQ': languages.AudioLanguage.es_GQ,
    'es-GT': languages.AudioLanguage.es_GT,
    'es-HN': languages.AudioLanguage.es_HN,
    'es-MX': languages.AudioLanguage.es_MX,
    'es-NI': languages.AudioLanguage.es_NI,
    'es-PA': languages.AudioLanguage.es_PA,
    'es-PE': languages.AudioLanguage.es_PE,
    'es-PR': languages.AudioLanguage.es_PR,
    'es-PY': languages.AudioLanguage.es_PY,
    'es-SV': languages.AudioLanguage.es_SV,
    'es-US': languages.AudioLanguage.es_US,
    'es-UY': languages.AudioLanguage.es_UY,
    'es-VE': languages.AudioLanguage.es_VE,
    'et-EE': languages.AudioLanguage.et_EE,
    'fa-IR': languages.AudioLanguage.fa_IR,
    'fi-FI': languages.AudioLanguage.fi_FI,
    'fil-PH': languages.AudioLanguage.fil_PH,
    'fr-BE': languages.AudioLanguage.fr_BE,
    'fr-CA': languages.AudioLanguage.fr_CA,
    'fr-CH': languages.AudioLanguage.fr_CH,
    'fr-FR': languages.AudioLanguage.fr_FR,
    'ga-IE': languages.AudioLanguage.ga_IE,
    'gl-ES': languages.AudioLanguage.gl_ES,
    'gu-IN': languages.AudioLanguage.gu_IN,
    'he-IL': languages.AudioLanguage.he_IL,
    'hi-IN': languages.AudioLanguage.hi_IN,
    'hr-HR': languages.AudioLanguage.hr_HR,
    'hu-HU': languages.AudioLanguage.hu_HU,
    'id-ID': languages.AudioLanguage.id_ID,
    'is-IS': languages.AudioLanguage.is_IS,
    'it-IT': languages.AudioLanguage.it_IT,
    'iu-Cans-CA': languages.AudioLanguage.iu_Cans_CA,
    'iu-Latn-CA': languages.AudioLanguage.iu_Latn_CA,
    'ja-JP': languages.AudioLanguage.ja_JP,
    'jv-ID': languages.AudioLanguage.jv_ID,
    'ka-GE': languages.AudioLanguage.ka_GE,
    'kk-KZ': languages.AudioLanguage.kk_KZ,
    'km-KH': languages.AudioLanguage.km_KH,
    'kn-IN': languages.AudioLanguage.kn_IN,
    'ko-KR': languages.AudioLanguage.ko_KR,
    'lo-LA': languages.AudioLanguage.lo_LA,
    'lt-LT': languages.AudioLanguage.lt_LT,
    'lv-LV': languages.AudioLanguage.lv_LV,
    'mk-MK': languages.AudioLanguage.mk_MK,
    'ml-IN': languages.AudioLanguage.ml_IN,
    'mn-MN': languages.AudioLanguage.mn_MN,
    'mr-IN': languages.AudioLanguage.mr_IN,
    'ms-MY': languages.AudioLanguage.ms_MY,
    'mt-MT': languages.AudioLanguage.mt_MT,
    'my-MM': languages.AudioLanguage.my_MM,
    'nb-NO': languages.AudioLanguage.nb_NO,
    'ne-NP': languages.AudioLanguage.ne_NP,
    'nl-BE': languages.AudioLanguage.nl_BE,
    'nl-NL': languages.AudioLanguage.nl_NL,
    'pl-PL': languages.AudioLanguage.pl_PL,
    'ps-AF': languages.AudioLanguage.ps_AF,
    'pt-BR': languages.AudioLanguage.pt_BR,
    'pt-PT': languages.AudioLanguage.pt_PT,
    'ro-RO': languages.AudioLanguage.ro_RO,
    'ru-RU': languages.AudioLanguage.ru_RU,
    'si-LK': languages.AudioLanguage.si_LK,
    'sk-SK': languages.AudioLanguage.sk_SK,
    'sl-SI': languages.AudioLanguage.sl_SI,
    'so-SO': languages.AudioLanguage.so_SO,
    'sq-AL': languages.AudioLanguage.sq_AL,
    'sr-RS': languages.AudioLanguage.sr_RS,
    'su-ID': languages.AudioLanguage.su_ID,
    'sv-SE': languages.AudioLanguage.sv_SE,
    'sw-KE': languages.AudioLanguage.sw_KE,
    'sw-TZ': languages.AudioLanguage.sw_TZ,
    'ta-IN': languages.AudioLanguage.ta_IN,
    'ta-LK': languages.AudioLanguage.ta_LK,
    'ta-MY': languages.AudioLanguage.ta_MY,
    'ta-SG': languages.AudioLanguage.ta_SG,
    'te-IN': languages.AudioLanguage.te_IN,
    'th-TH': languages.AudioLanguage.th_TH,
    'tr-TR': languages.AudioLanguage.tr_TR,
    'uk-UA': languages.AudioLanguage.uk_UA,
    'ur-IN': languages.AudioLanguage.ur_IN,
    'ur-PK': languages.AudioLanguage.ur_PK,
    'uz-UZ': languages.AudioLanguage.uz_UZ,
    'vi-VN': languages.AudioLanguage.vi_VN,
    'zh-CN': languages.AudioLanguage.zh_CN,
    'zh-CN-liaoning': languages.AudioLanguage.zh_CN_liaoning,
    'zh-CN-shaanxi': languages.AudioLanguage.zh_CN_shaanxi,
    'zh-HK': languages.AudioLanguage.zh_HK,
    'zh-TW': languages.AudioLanguage.zh_TW,
    'zu-ZA': languages.AudioLanguage.zu_ZA,
}


def _find_edge_tts():
    """Find the edge-tts command."""
    import shutil
    path = shutil.which('edge-tts')
    if path:
        return path
    return None


class EdgeTTS(service.ServiceBase):

    def __init__(self):
        service.ServiceBase.__init__(self)

    @property
    def service_type(self) -> constants.ServiceType:
        return constants.ServiceType.tts

    @property
    def service_fee(self) -> constants.ServiceFee:
        return constants.ServiceFee.free

    def enabled_by_default(self):
        return False

    def cloudlanguagetools_enabled(self):
        return False

    def voice_list(self):
        edge_tts_cmd = _find_edge_tts()
        if edge_tts_cmd is None:
            logger.warning('EdgeTTS: edge-tts command not found in PATH')
            return []

        voice_options = {
            'rate': {
                'type': 'number',
                'min': -90.0,
                'max': 200.0,
                'default': 0.0,
            },
            'volume': {
                'type': 'number',
                'min': -90.0,
                'max': 100.0,
                'default': 0.0,
            },
            'pitch': {
                'type': 'number',
                'min': -50.0,
                'max': 50.0,
                'default': 0.0,
            },
        }

        try:
            result = subprocess.run(
                [edge_tts_cmd, '--list-voices'],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.error('EdgeTTS: --list-voices timed out')
            return []
        except Exception as e:
            logger.error(f'EdgeTTS: failed to run --list-voices: {e}')
            return []

        if result.returncode != 0:
            logger.error(f'EdgeTTS: --list-voices failed: {result.stderr}')
            return []

        return self._parse_voice_list(result.stdout, voice_options)

    def _parse_voice_list(self, output, voice_options):
        result = []
        lines = output.strip().split('\n')

        for line in lines[2:]:
            parts = line.split()
            if len(parts) < 2:
                continue

            short_name = parts[0]
            gender_str = parts[1]

            locale = '-'.join(short_name.split('-')[:2])
            audio_language = LOCALE_TO_AUDIO_LANGUAGE.get(locale)
            if audio_language is None:
                continue

            if gender_str == 'Male':
                gender = constants.Gender.Male
            elif gender_str == 'Female':
                gender = constants.Gender.Female
            else:
                gender = constants.Gender.Any

            # Build friendly name from short name
            # e.g. "en-US-AvaNeural" -> "AvaNeural (en-US)"
            name_part = short_name.split('-', 2)[-1] if '-' in short_name else short_name
            display_name = f'{name_part} ({locale})'

            result.append(voice.TtsVoice_v3(
                name=display_name,
                gender=gender,
                audio_languages=[audio_language],
                service=self.name,
                voice_key=short_name,
                options=voice_options,
                service_fee=self.service_fee,
            ))

        return result

    def get_tts_audio(self, source_text, voice: voice.TtsVoice_v3, voice_options):
        edge_tts_cmd = _find_edge_tts()
        if edge_tts_cmd is None:
            raise errors.RequestError(source_text, voice, 'EdgeTTS: edge-tts command not found in PATH')

        rate = voice_options.get('rate', voice.options['rate']['default'])
        volume = voice_options.get('volume', voice.options['volume']['default'])
        pitch = voice_options.get('pitch', voice.options['pitch']['default'])

        rate_str = f'{rate:+.0f}%' if rate != 0 else '+0%'
        volume_str = f'{volume:+.0f}%' if volume != 0 else '+0%'
        pitch_str = f'{pitch:+.0f}Hz' if pitch != 0 else '+0Hz'

        short_name = voice.voice_key

        fh, temp_file = tempfile.mkstemp(prefix='hypertts_edge_', suffix='.mp3')
        os.close(fh)

        try:
            cmd = [
                edge_tts_cmd,
                '--text', source_text,
                '--voice', short_name,
                '--rate', rate_str,
                '--volume', volume_str,
                '--pitch', pitch_str,
                '--write-media', temp_file,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f'edge-tts exited with code {result.returncode}'
                raise errors.RequestError(source_text, voice, f'EdgeTTS error: {error_msg}')

            with open(temp_file, 'rb') as f:
                audio = f.read()

            if not audio:
                raise errors.RequestError(source_text, voice, 'EdgeTTS returned no audio')

            return audio

        except subprocess.TimeoutExpired:
            raise errors.RequestError(source_text, voice, 'EdgeTTS: request timed out')
        except errors.RequestError:
            raise
        except Exception as e:
            raise errors.RequestError(source_text, voice, f'EdgeTTS error: {e}')
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)
