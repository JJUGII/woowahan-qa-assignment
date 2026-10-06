from airtest.core.api import connect_device, G, set_current
import logging

logger = logging.getLogger(__name__)


def init_airtest(udid: str):
    """안전한 Airtest 세션 초기화 로직"""
    try:
        # 이미 연결된 디바이스 리스트 확인
        for dev in G.DEVICE_LIST:
            if dev.serial == udid:
                set_current(udid)
                return dev

        # 신규 연결 (ADB 경로를 명시적으로 지정하면 더 안정적입니다)
        uri = f"android://127.0.0.1:5037/{udid}?cap_method=JAVASCREENCAP"
        dev = connect_device(uri)
        set_current(dev)
        logger.info(f"[{udid}] Airtest 연결 성공")
        return dev
    except Exception as e:
        logger.error(f"[{udid}] Airtest 초기화 실패. Error: {e}")
        return None