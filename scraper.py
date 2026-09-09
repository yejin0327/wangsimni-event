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
    return re.sub(
        r"\s+",
        " ",
        text.replace("\xa0", " ")
    ).strip()


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


def parse_price(text):
    text = clean(text)

    # 할인율 + 가격 + 정상가
    match = re.search(
        r"(\d+)\s*%\s*"
        r"([\d,]+)\s*원"
        r"(?:\s*~~\s*([\d,]+)\s*~~\s*원)?",
        text
    )

    if match:
        return {
            "price": int(
                match.group(2).replace(",", "")
            ),
            "normal": (
                int(
                    match.group(3).replace(",", "")
                )
                if match.group(3)
                else None
            ),
            "discount": int(match.group(1)),
        }

    # 할인율 없는 옵션 가격
    match = re.fullmatch(
        r"([\d,]+)\s*원",
        text
    )

    if match:
        return {
            "price": int(
                match.group(1).replace(",", "")
            ),
            "normal": None,
            "discount": None,
        }

    return None


def is_price(text):
    return parse_price(text) is not None


def extract_from_container(container, category_id):

    lines = []

    for line in container.stripped_strings:
        line = clean(line)

        if line:
            lines.append(line)

    events = []

    source = (
        BASE_URL
        + "?tb=event_multi"
        + "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
        + f"&sField={category_id}"
    )

    # 가격이 있는 줄을 찾습니다.
    for i, line in enumerate(lines):

        price = parse_price(line)

        if not price:
            continue

        # 가격 바로 위쪽에서 가장 가까운
        # 상품명 후보를 찾습니다.
        name = None

        for j in range(
            i - 1,
            max(-1, i - 8),
            -1
        ):

            candidate = clean(lines[j])

            if not candidate:
                continue

            if is_price(candidate):
                continue

            if candidate.startswith("※"):
                continue

            if candidate in [
                "왕십리점",
                "보기 토글",
                "패키지 보기 토글",
            ]:
                continue

            # 날짜
            if re.fullmatch(
                r"\d{4}-\d{2}-\d{2}까지",
                candidate
            ):
                continue

            name = candidate.lstrip("*").strip()
            break

        if not name:
            continue

        events.append({
            "category": CATEGORIES[category_id],
            "name": name,
            "price": price["price"],
            "normal": price["normal"],
            "discount": price["discount"],
            "option": (
                name.startswith("옵션")
                or name.startswith("추가")
            ),
            "source": source,
        })

    return events


def scrape_category(category_id):

    html = fetch(category_id)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # script/style 제거
    for tag in soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    events = []

    # -------------------------------------------------
    # 1차: HTML 요소별로 이벤트 영역 탐색
    # -------------------------------------------------

    for element in soup.find_all(
        ["li", "article", "div", "section"]
    ):

        text = clean(
            element.get_text(" ", strip=True)
        )

        # 너무 큰 부모 영역은 제외
        if len(text) > 8000:
            continue

        # 가격이 최소 하나 들어있는 영역만 검사
        if not re.search(
            r"\d[\d,]*\s*원",
            text
        ):
            continue

        found = extract_from_container(
            element,
            category_id
        )

        events.extend(found)


    # -------------------------------------------------
    # 2차: 페이지 전체 텍스트 fallback
    # -------------------------------------------------

    if not events:

        lines = [
            clean(x)
            for x in soup.get_text("\n").splitlines()
            if clean(x)
        ]

        fake_html = (
            "<div>"
            + "".join(
                f"<div>{line}</div>"
                for line in lines
            )
            + "</div>"
        )

        fake_soup = BeautifulSoup(
            fake_html,
            "html.parser"
        )

        events.extend(
            extract_from_container(
                fake_soup.div,
                category_id
            )
        )


    return events


def deduplicate(events):

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
    print(" 왕십리점 이벤트 자동 수집")
    print("==============================")
    print("")

    all_events = []

    for category_id in CATEGORIES:

        category = CATEGORIES[
            category_id
        ]

        print(
            f"[{category_id}/7] "
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

        except Exception as error:

            print(
                f"  오류: {error}"
            )


    all_events = deduplicate(
        all_events
    )


    if not all_events:

        raise RuntimeError(
            "이벤트를 찾지 못했습니다."
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
        encoding="utf-8"
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
            event
            for event in all_events
            if keyword.lower()
            in event["name"].lower()
        ]

        print(
            f"{keyword}: "
            f"{len(matches)}개"
        )

        if keyword == "슈링크":

            for event in matches[:10]:

                print(
                    "  ",
                    event["name"],
                    "→",
                    f'{event["price"]:,}원'
                )


if __name__ == "__main__":
    main()
