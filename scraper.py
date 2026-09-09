import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.velyb.kr/community/community01.php"
OUTPUT = Path("events.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


CATEGORIES = {
    1: "기획전",
    2: "쁘띠성형",
    3: "피부",
    4: "리프팅",
    5: "부스터",
    6: "제모",
    7: "비만",
}


def clean(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch(category_id):
    response = requests.get(
        BASE_URL,
        params={
            "tb": "event_multi",
            "etc5": "왕십리점",
            "sField": category_id,
        },
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    return response.text


def price_info(text):
    """
    할인율 + 이벤트가 + 정상가

    예:
    48% 12,900원 ~~25,200~~원
    """

    m = re.search(
        r"(\d+)\s*%\s*"
        r"([\d,]+)\s*원"
        r"(?:\s*~~\s*([\d,]+)\s*~~\s*원)?",
        text,
    )

    if m:
        return {
            "discount": int(m.group(1)),
            "price": int(
                m.group(2).replace(",", "")
            ),
            "normal": (
                int(
                    m.group(3).replace(",", "")
                )
                if m.group(3)
                else None
            ),
        }

    # 옵션처럼 할인율이 없는 가격
    m = re.search(
        r"^([\d,]+)\s*원$",
        text,
    )

    if m:
        return {
            "discount": None,
            "price": int(
                m.group(1).replace(",", "")
            ),
            "normal": None,
        }

    return None


def useless_line(text):
    """
    상품명이 아닌 UI/설명 문구인지 확인
    """

    if not text:
        return True

    bad = [
        "왕십리점",
        "지점안내",
        "온라인상담",
        "전화상담신청",
        "보기 토글",
        "패키지 보기 토글",
        "전체시술",
        "기획전",
        "쁘띠성형",
        "피부",
        "리프팅",
        "부스터",
        "제모",
        "비만",
        "로그인",
        "회원가입",
        "EVENT",
        "NEW",
    ]

    if text in bad:
        return True

    if text.startswith("※"):
        return True

    # 날짜
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}까지",
        text,
    ):
        return True

    # 가격 자체
    if price_info(text):
        return True

    # 너무 긴 설명문
    if len(text) > 180:
        return True

    return False


def get_text_lines(html):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    lines = []

    for line in soup.get_text("\n").splitlines():

        line = clean(line)

        if line:
            lines.append(line)

    return lines


def find_name(lines, price_index):
    """
    가격 줄 위쪽에서 실제 상품명을 찾습니다.

    실제 페이지는:

    상품명
    설명
    * 상품명
    할인율 가격

    형태도 있기 때문에 최대 12줄까지
    위로 올라가며 찾습니다.
    """

    # 가장 가까운 줄부터 탐색
    for distance in range(1, 13):

        index = price_index - distance

        if index < 0:
            break

        line = clean(lines[index])

        if not line:
            continue

        # 날짜를 만나면 현재 이벤트 영역 종료
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}까지",
            line,
        ):
            break

        if useless_line(line):
            continue

        # 설명 문구는 건너뜁니다.
        description_words = [
            "피부 상태에 따라",
            "피부 깊은층",
            "피부의",
            "기존의",
            "극초단파를 이용한",
            "빈틈없이 꼼꼼하게",
            "한번에",
            "고민을",
            "효과를",
            "시술입니다",
        ]

        if any(
            word in line
            for word in description_words
        ):
            continue

        # 상품명 후보
        return line.lstrip("*").strip()

    return None


def scrape_category(category_id):

    html = fetch(category_id)
    lines = get_text_lines(html)

    events = []

    source = (
        BASE_URL
        + "?tb=event_multi"
        + "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
        + f"&sField={category_id}"
    )

    for i, line in enumerate(lines):

        info = price_info(line)

        if not info:
            continue

        name = find_name(
            lines,
            i,
        )

        if not name:
            continue

        # 너무 일반적인 이름 제외
        if len(name) < 2:
            continue

        event = {
            "category": CATEGORIES[
                category_id
            ],
            "name": name,
            "price": info["price"],
            "normal": info["normal"],
            "discount": info["discount"],
            "option": (
                name.startswith("옵션")
                or name.startswith("추가")
            ),
            "source": source,
        }

        events.append(event)

    return events


def remove_duplicates(events):

    result = []
    seen = set()

    for event in events:

        key = (
            event["category"],
            event["name"],
            event["price"],
            event["normal"],
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(event)

    return result


def main():

    print("")
    print("==============================")
    print(" 블리비 왕십리점 이벤트 수집")
    print("==============================")
    print("")

    all_events = []

    for category_id in range(1, 8):

        category = CATEGORIES[
            category_id
        ]

        print(
            f"{category} 수집 중..."
        )

        try:

            events = scrape_category(
                category_id
            )

            print(
                f"  발견: {len(events)}개"
            )

            all_events.extend(events)

        except Exception as e:

            print(
                f"  오류: {e}"
            )

    all_events = remove_duplicates(
        all_events
    )

    if not all_events:
        raise RuntimeError(
            "수집된 이벤트가 없습니다."
        )

    collected_at = (
        datetime.now(
            timezone.utc
        )
        .astimezone()
        .isoformat()
    )

    for event in all_events:
        event["collected_at"] = (
            collected_at
        )

    all_events.sort(
        key=lambda x: (
            x["category"],
            x["name"],
            x["price"] or 0,
        )
    )

    OUTPUT.write_text(
        json.dumps(
            all_events,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("")
    print("==============================")
    print(
        f"수집 완료: {len(all_events)}개"
    )
    print("==============================")
    print("")

    # 검색 테스트
    for keyword in [
        "슈링크",
        "울쎄라",
        "인모드",
        "보톡스",
        "필러",
        "제모",
    ]:

        matches = [
            x
            for x in all_events
            if keyword in x["name"]
        ]

        print(
            f"{keyword}: {len(matches)}개"
        )

        if keyword == "슈링크":

            for item in matches[:5]:

                print(
                    "  -",
                    item["name"],
                    "|",
                    f'{item["price"]:,}원',
                )


if __name__ == "__main__":
    main()
