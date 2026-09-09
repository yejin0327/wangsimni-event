import json
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = (
    "https://www.velyb.kr/community/community01.php"
    "?tb=event_multi"
    "&etc5=%EC%99%95%EC%8B%AD%EB%A6%AC%EC%A0%90"
    "&sField=6"
)

OUTPUT = Path("events.json")


def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()


def price_to_number(text):
    if not text:
        return None

    match = re.search(r"([\d,]+)\s*원", text)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def discount_to_number(text):
    if not text:
        return None

    match = re.search(r"(\d+)\s*%", text)

    if not match:
        return None

    return int(match.group(1))


def find_prices(text):
    prices = re.findall(
        r"[\d,]+\s*원",
        text
    )

    result = []

    for price in prices:
        number = price_to_number(price)

        if number is not None and number not in result:
            result.append(number)

    return result


def detect_category(text):

    categories = [
        "쁘띠성형",
        "피부",
        "리프팅",
        "부스터",
        "제모",
        "비만",
        "기획전",
    ]

    for category in categories:
        if category in text:
            return category

    return "전체"


def is_option(text):
    option_words = [
        "옵션",
        "추가",
        "선택",
    ]

    return any(
        word in text
        for word in option_words
    )


def scrape():

    headers = {
        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/130 Safari/537.36"
    }

    response = requests.get(
        URL,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    events = []

    # 이벤트 게시물 영역을 우선 탐색
    candidates = soup.select(
        "li, article, .event, .event_list, .board_list"
    )

    seen = set()

    for element in candidates:

        text = clean_text(
            element.get_text(" ", strip=True)
        )

        if len(text) < 10:
            continue

        prices = find_prices(text)

        if not prices:
            continue

        # 너무 큰 영역은 전체 페이지일 가능성이 있으므로 제외
        if len(text) > 1500:
            continue

        # 할인율
        discount = discount_to_number(text)

        # 이벤트명
        title = None

        title_selectors = [
            "h1",
            "h2",
            "h3",
            "h4",
            ".title",
            ".tit",
            ".subject",
            ".event_title",
        ]

        for selector in title_selectors:

            node = element.select_one(selector)

            if node:

                candidate = clean_text(
                    node.get_text(
                        " ",
                        strip=True
                    )
                )

                if len(candidate) >= 2:
                    title = candidate
                    break

        if not title:
            title = text[:120]

        # 가격
        event_price = prices[0]

        normal_price = (
            prices[1]
            if len(prices) > 1
            else None
        )

        category = detect_category(text)

        option = is_option(title)

        key = (
            title,
            event_price,
            normal_price
        )

        if key in seen:
            continue

        seen.add(key)

        events.append({
            "category": category,
            "name": title,
            "price": event_price,
            "normal": normal_price,
            "discount": discount,
            "option": option,
            "source": URL,
            "collected_at":
                datetime.now().isoformat()
        })

    # 가격이 있는 이벤트가 하나도 없으면
    # 잘못된 파싱으로 판단하여 기존 데이터 보호
    if not events:
        raise RuntimeError(
            "이벤트 데이터를 찾지 못했습니다."
        )

    OUTPUT.write_text(
        json.dumps(
            events,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"수집 완료: {len(events)}개"
    )


if __name__ == "__main__":
    scrape()
