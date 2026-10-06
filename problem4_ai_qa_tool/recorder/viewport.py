"""One image-space mapping for taps, XML selection, swipes and crop centers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RecorderViewport:
    image_width: int
    image_height: int
    device_width: int
    device_height: int
    width: int
    height: int

    @classmethod
    def create(cls, image_width, image_height, device_width, device_height):
        if min(image_width, image_height, device_width, device_height) <= 0:
            raise ValueError('화면 크기를 확인할 수 없습니다.')
        # wm size stays portrait when Android rotates; screenshots follow the display.
        if (image_width > image_height) != (device_width > device_height):
            device_width, device_height = device_height, device_width
        ratio = min(720 / image_height, 840 / image_width)
        return cls(image_width, image_height, device_width, device_height,
                   max(1, int(image_width * ratio)), max(1, int(image_height * ratio)))

    def point(self, x, y, *, image=False):
        # HighGUI WIN32 WINDOW_NORMAL already converts client coordinates to image
        # coordinates. Do not apply the resized native window's scale a second time.
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        width, height = ((self.image_width, self.image_height) if image else
                         (self.device_width, self.device_height))
        return min(width-1, int(x * width / self.width)), min(height-1, int(y * height / self.height))


def recorder_shortcut(key):
    """Keep Unicode intact, accept capitals; ignore unsupported/extended key codes."""
    if key == 27:
        return 'BACK'
    if key < 0 or key > 0x10FFFF:
        return None
    return {'a':'ASSERT', 'ㅁ':'ASSERT', 'c':'CLICK', 'ㅊ':'CLICK', 'i':'INPUT', 'ㅑ':'INPUT',
            't':'SLEEP', 'ㅅ':'SLEEP', 'b':'BACK', 'ㅠ':'BACK', 'q':'SAVE', 'ㅂ':'SAVE'}.get(chr(key).lower())
