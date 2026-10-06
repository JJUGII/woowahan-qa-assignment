import xml.etree.ElementTree as ET
import re


def parse_bounds(bounds_str: str) -> tuple:
    """ '[0,0][1080,2400]' 형태의 문자열을 좌표 튜플로 변환 """
    match = re.fullmatch(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]', bounds_str)
    if match:
        return tuple(map(int, match.groups()))
    return (0, 0, 0, 0)


def get_element_by_click(xml_source: str, click_x: int, click_y: int) -> dict:
    """
    클릭한 좌표(x, y)를 포함하는 가장 하위 XML 노드를 찾아서 반환
    """
    root = ET.fromstring(xml_source)
    target_element = None
    min_area = float('inf')

    # 모든 노드를 순회하며 클릭 좌표가 bounds 안에 있는지 확인
    for node in root.iter():
        bounds_str = node.attrib.get('bounds')
        if not bounds_str:
            continue

        x1, y1, x2, y2 = parse_bounds(bounds_str)

        if x1 <= click_x < x2 and y1 <= click_y < y2:
            area = (x2 - x1) * (y2 - y1)
            # 가장 좁은 영역(가장 구체적인 버튼/텍스트)을 찾음
            if area > 0 and area < min_area:
                min_area = area
                target_element = node.attrib

    # 추출된 엘리먼트 정보 포맷팅
    if target_element:
        # Keep accessibility labels and state attributes for recommendation/validation.
        return dict(target_element)
    return None
