from .env import LOG_LEVEL

from notion_client import Client
from notion_client.helpers import iterate_paginated_api
from typing import List, Dict, Any, Union
import logging
import re


def create_simple_logger(name, level=LOG_LEVEL):
    """Creates a simple loger that outputs to stdout"""
    level_to_int_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    if isinstance(level, str):
        level = level_to_int_map[level.lower()]
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if logger.hasHandlers():
        logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = create_simple_logger(__name__)


def remove_link(title: str) -> str:
    if "](" in title:
        title = title.split("](")[0]
        title = title[1:]  # remove the first [
    return title


def remove_bold_from_title(title: str) -> str:
    title = remove_link(title)
    # remove strting or trailing *s
    p = r"^[*]{1,}|[*]{1,}\s?$"
    title = re.sub(p, "", title)
    return title


def create_href(title: str) -> str:
    title = remove_bold_from_title(title)
    title = title.lower()
    title = title.replace(" ", "-")
    return title


def create_table_of_content_from_markdown_file(markdown: str) -> str:
    headings = []
    for line in markdown.split("\n"):
        if line.startswith("#"):
            level = len(line.split(" ")[0])
            title = line.replace("#", "").strip()
            headings.append((level, title))
    toc = ""
    for level, title in headings:
        title_og = remove_bold_from_title(title)
        # lower and replace spaces with -
        title = create_href(title)
        indent = "    " * (level - 1)
        toc += f"{indent}- [{title_og}](#{title})\n"
    return toc


def get_all_childrens(notion: Client, block_id: str) -> List[Dict[str, Any]]:
    children = []
    for child in iterate_paginated_api(notion.blocks.children.list, block_id=block_id):
        children.append(child)
    return children


def rich_text_to_markdown(
    rich_text_dict: Dict[str, Union[Dict[str, Any], str, bool]]
) -> str:
    """rich_text_dict: The dictionary containing the rich text data from Notion API"""
    type_ = rich_text_dict.get("type", "text")
    # each rich text has `plain_text` which is equivalent to its content
    # https://developers.notion.com/reference/rich-text
    plain_text = rich_text_dict.get("plain_text", "")

    # inline the expression, return the plain text wrapped in $
    if type_ == "equation":
        return f"${plain_text}$"

    annotations = rich_text_dict.get("annotations", {})
    bold = annotations.get("bold", False)
    italic = annotations.get("italic", False)
    strikethrough = annotations.get("strikethrough", False)
    underline = annotations.get("underline", False)
    href = rich_text_dict.get("href", None)

    if bold:
        plain_text = f"**{plain_text.strip()}**"
    if italic:
        plain_text = f"*{plain_text.strip()}*"
    if strikethrough:
        plain_text = f"~~{plain_text.strip()}~~"
    if underline:
        plain_text = f"<u>{plain_text.strip()}</u>"
    if href:
        plain_text = f"[{plain_text}]({href})"
    return plain_text
