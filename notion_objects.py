from notion_client import Client
from notion_client.helpers import iterate_paginated_api
from typing import List, Dict, Any, Union, Optional

from IPython.display import display, Markdown
import logging
import re
from env import NOTION_SECRET_KEY, LOG_LEVEL

notion = Client(auth=NOTION_SECRET_KEY)


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
    if type_ == "text":
        text = rich_text_dict[type_].get("content", "")
    elif type_ == "equation":  # inline the expression
        text = rich_text_dict[type_].get("expression", "")
        return f"${text}$"
    text = rich_text_dict[type_].get("content", "")
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


class Block:

    def __init__(self, block_id: str, block_dict: Optional[Dict[str, Any]] = None):
        self.logger = create_simple_logger(__name__ + "." + self.__class__.__name__)
        self.block_id = block_id
        self.block_dict = block_dict or notion.blocks.retrieve(block_id=self.block_id)
        self._has_children: bool = None
        self._children: Optional[List[Block]] = None
        self._type: str = None
        self._parent: Optional["Block"] = None

    def __repr__(self):
        return f"{self.__class__.__name__}(block_id={self.block_id}, type={self.type})"

    def __str__(self):
        return f"{self.__class__.__name__}(block_id={self.block_id}, type={self.type})"

    def __getitem__(self, key):
        return self.block_dict[key]

    @property
    def children(self) -> List["Block"]:
        if self.has_children is False:
            self.logger.debug(f"{self} has no children")
            return []

        if self._children is None:
            self._children_dict = get_all_childrens(
                notion=notion, block_id=self.block_id
            )
            # create block objects
            self._children = [
                Block(child["id"], child) for child in self._children_dict
            ]
        return self._children

    @property
    def type(self) -> str:
        if self._type is None:
            try:
                self._type = self.block_dict["type"]
            except KeyError as e:
                self.logger.warning(
                    f"Key `type` not found in block_dict: {self.block_dict}. Setting type to `unknown`"
                )
                self._type = "unknown"
        return self._type

    @property
    def has_children(self) -> bool:
        if self._has_children is None:
            self._has_children = self.block_dict.get("has_children", False)
        return self._has_children

    @property
    def parent(self) -> Optional["Block"]:
        if self._parent is None:
            parent_id = self.block_dict.get("parent", {}).get("id", None)
            if parent_id is not None:
                self._parent = Block(parent_id)
        return self._parent

    def different_types_in_children(self):
        return set([child.type for child in self.children])

    def filter_children_by_type(self, block_type: str):
        return [child for child in self.children if child.type == block_type]


class BlockParser:
    def __init__(
        self, block: Optional[Block] = None, raw_dict: Optional[Dict[str, Any]] = None
    ) -> None:
        self.logger = create_simple_logger(__name__ + "." + self.__class__.__name__)
        if block is None and raw_dict is None:
            m = "Either block or raw_dict should be provided"
            self.logger.error(m)
            raise ValueError(m)
        if block is not None:
            raw_dict = block.block_dict

        if "type" not in raw_dict:
            m = "The dictionary doesn't contain a 'type' key"
            self.logger.error(m)
            raise ValueError(m)

        self.block = block
        self.type = raw_dict["type"]
        self.logger.debug(
            f"Creating a {self.__class__.__name__} object for '{self.type}' type"
        )
        self.raw_dict = raw_dict

        if self.type not in self.raw_dict:
            m = f"The dictionary doesn't contain a '{self.type}' key"
            self.logger.error(m)
            raise ValueError(m)

        self.text_dict = raw_dict[self.type]
        has_children = raw_dict.get("has_children", False)
        if has_children:
            self.logger.debug("The block has children")
        self.name = ""
        self.markdown_text = self.convert_to_markdown()

    def _rich_texts_to_markdown(
        self, rich_texts: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> str:
        if isinstance(rich_texts, dict):
            return rich_text_to_markdown(rich_texts)

        return "".join([rich_text_to_markdown(r) for r in rich_texts])

    def convert_to_markdown(self) -> str:
        raise NotImplementedError(
            "This method needs to be implemented in the child class"
        )

    def show_markdown(self):
        display(Markdown(self.markdown_text))


class Paragraph(BlockParser):
    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        return self._rich_texts_to_markdown(rich_texts)


class Quote(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        string = self._rich_texts_to_markdown(rich_texts)
        return f"> {string}"


class UnOrderedList(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        string = self._rich_texts_to_markdown(rich_texts)
        return f"- {string}"


class OrderedList(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
        number: int = 1,
    ):
        self.number = number
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        string = self._rich_texts_to_markdown(rich_texts)
        return f"{self.number}. {string}"


class TableRow(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        cells = self.text_dict.get("cells", [[]])  # a list of list of rich texts
        x = " | ".join([self._rich_texts_to_markdown(cell) for cell in cells])
        # add the first and last |
        return f"| {x} |"


class Table(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        table_children = self.block.children
        if len(table_children) == 0:
            return ""

        # header row
        header_row = table_children[0]
        header_row_markdown = TableRow(header_row).convert_to_markdown()
        # create the separator row
        cells = (
            header_row_markdown.count("|") - 1
        )  # number of cells is 1 less than the number of |
        separator_row = "|".join(["---"] * cells)
        separator_row = f"| {separator_row} |"
        # other rows
        other_rows = table_children[1:]
        other_rows_markdown = [
            TableRow(row).convert_to_markdown() for row in other_rows
        ]
        return "\n".join([header_row_markdown, separator_row] + other_rows_markdown)


class Heading(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
        shift_by: int = 1,
    ):
        # shift the heading level by this number
        # by default 1 because the title of the page should be level 1
        self.shift_by = shift_by
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        string = self._rich_texts_to_markdown(rich_texts)
        # remove bold from string
        string = remove_bold_from_title(string)
        string = string.strip()
        level = int(self.type.split("_")[-1]) + self.shift_by
        level = min(4, level)  # max heading level is 4
        return f"{'#' * level} {string}"


class Equation(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        expression = self.text_dict.get("expression", "")
        return f"$$ {expression} $$"


class Paragraph(BlockParser):
    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        rich_texts = self.text_dict.get("rich_text", [])
        return self._rich_texts_to_markdown(rich_texts)


class Image(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        url = self.text_dict.get("file", {}).get("url", "")
        caption = self.text_dict.get("caption", [])
        caption = self._rich_texts_to_markdown(caption)
        return f"![{caption}]({url})"


class ChildPage(BlockParser):

    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        title = self.text_dict.get("title", "")
        self.name = title
        id_ = self.block.block_id.replace("-", "")
        return f"# [{title}](https://www.notion.so/{id_})"


class Bookmark(BlockParser):
    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        caption = self.text_dict.get("caption", [])
        if caption:
            caption = self._rich_texts_to_markdown(caption)
        else:
            caption = ""

        url = self.text_dict.get("url", "")
        if caption == "":
            caption = url
        return f"- [{caption}]({url})"


class Code(BlockParser):
    def __init__(
        self,
        block: Optional[Block] = None,
        raw_dict: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(block, raw_dict)

    def convert_to_markdown(self):
        code = self.text_dict.get("rich_text", [])
        language = self.text_dict.get("language", "plain text")
        code = self._rich_texts_to_markdown(code)
        return f"```{language}\n{code}\n```"


block_type_to_parser_map = {
    "paragraph": Paragraph,
    "quote": Quote,
    "bulleted_list_item": UnOrderedList,
    "numbered_list_item": OrderedList,
    "table_of_contents": Paragraph,
    "table": Table,
    "heading_1": Heading,
    "heading_2": Heading,
    "heading_3": Heading,
    "equation": Equation,
    "toggle": Paragraph,
    "image": Image,
    "child_page": ChildPage,
    "bookmark": Bookmark,
    "code": Code,
    "divider": Divider,
    "column_list": Empty,  # not creating columns. Each column will be parsed separately
    "column": Empty,  ## not creating columns. Each column will be parsed separately
}

types_to_ignore = ["table_row", "column"]


class Parser:
    def __init__(self, root_block: Block, max_depth: int = 5):
        self.root_block = root_block
        self.max_depth = max_depth
        self.logger = create_simple_logger(__name__ + "." + self.__class__.__name__)
        self.markdown_text = ""

    def parse_block(self, block: Block, parent_child_same_type: int = 0):
        block_type = block.type

        if block_type in types_to_ignore:
            self.logger.debug(f"Ignoring block type '{block_type}'")
            return

        parser = block_type_to_parser_map.get(block_type, None)
        if parser is None:
            self.logger.warning(f"No parser found for block type '{block_type}'")
            return
        parser_instance: BlockParser = parser(block)
        if block_type in ["child_page"]:
            m = f"Starting to parse a {block_type} block"
            if parser_instance.name:
                m += f" with title: {parser_instance.name}"
            self.logger.info(m)

        markdown = parser_instance.markdown_text
        markdown = "    " * parent_child_same_type + markdown
        self.markdown_text += markdown + "\n\n"

    def parse(
        self,
        block: Optional[Block] = None,
        depth: int = 0,
        parent_child_same_type: int = 0,
    ):
        if depth > self.max_depth:
            self.logger.warning(f"Max depth reached. Stopping parsing for {block}")
            return

        if block is None:
            block = self.root_block

        self.parse_block(block, parent_child_same_type)
        # if the block has childrens, parse them recursively
        if block.has_children:
            # in case the parent and child have the same type, we want to indent the child
            # For example, if the parent is a list item and the child is also a list item
            # we want to indent the child so that it looks like a nested list
            if block.children[0].type == block.type and block.type in [
                "bulleted_list_item",
                "numbered_list_item",
            ]:
                parent_child_same_type += 1

            for child in block.children:
                self.parse(child, depth + 1, parent_child_same_type)

    def clean_text(self):
        self.markdown_text = re.sub(r"\n{3,}", "\n\n", self.markdown_text)
        # remove starting new lines
        self.markdown_text = self.markdown_text.strip()
        # add a new line at the end
        self.markdown_text += "\n"

    def parse_and_save(self, save_path: str, add_toc: bool = True):
        self.parse(self.root_block)
        self.clean_text()
        if add_toc:
            toc = create_table_of_content_from_markdown_file(self.markdown_text)
            self.markdown_text = toc + "\n\n" + self.markdown_text
        with open(save_path, "w") as f:
            f.write(self.markdown_text)
        self.logger.info(f"Markdown saved to '{save_path}'")
