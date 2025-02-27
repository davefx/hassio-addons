"""Classes for representing sentence templates."""

import re
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterator, List, Optional


@dataclass
class Expression(ABC):
    """Base class for expressions."""


@dataclass
class TextChunk(Expression):
    """Contiguous chunk of text (with whitespace)."""

    # Text with casing/whitespace normalized
    text: str = ""

    # Set in __post_init__
    original_text: str = None  # type: ignore

    parent: "Optional[Sequence]" = None

    def __post_init__(self):
        if self.original_text is None:
            self.original_text = self.text

    @property
    def is_empty(self) -> bool:
        """True if the chunk is empty"""
        return self.text == ""

    @staticmethod
    def empty() -> "TextChunk":
        """Returns an empty text chunk"""
        return TextChunk()


class SequenceType(str, Enum):
    """Type of a sequence. Optionals are alternatives with an empty option."""

    # Sequence of expressions
    GROUP = "group"

    # Expressions where only one will be recognized
    ALTERNATIVE = "alternative"

    # Permutations of a set of expressions
    PERMUTATION = "permutation"


@dataclass
class Sequence(Expression):
    """Ordered sequence of expressions. Supports groups, optionals, and alternatives."""

    # Items in the sequence
    items: List[Expression] = field(default_factory=list)

    # Group or alternative
    type: SequenceType = SequenceType.GROUP

    is_optional: bool = False

    def text_chunk_count(self) -> int:
        """Return the number of TextChunk expressions in this sequence (recursive)."""
        num_text_chunks = 0
        for item in self.items:
            if isinstance(item, TextChunk):
                num_text_chunks += 1
            elif isinstance(item, Sequence):
                seq: Sequence = item
                num_text_chunks += seq.text_chunk_count()

        return num_text_chunks

    def list_names(
        self,
        expansion_rules: Optional[Dict[str, "Sentence"]] = None,
    ) -> Iterator[str]:
        """Return names of list references (recursive)."""
        for item in self.items:
            yield from self._list_names(item, expansion_rules)

    def _list_names(
        self,
        item: Expression,
        expansion_rules: Optional[Dict[str, "Sentence"]] = None,
    ) -> Iterator[str]:
        """Return names of list references (recursive)."""
        if isinstance(item, ListReference):
            list_ref: ListReference = item
            yield list_ref.list_name
        elif isinstance(item, Sequence):
            seq: Sequence = item
            yield from seq.list_names(expansion_rules)
        elif isinstance(item, RuleReference):
            rule_ref: RuleReference = item
            if expansion_rules and (rule_ref.rule_name in expansion_rules):
                rule_body = expansion_rules[rule_ref.rule_name]
                yield from self._list_names(rule_body, expansion_rules)


@dataclass
class RuleReference(Expression):
    """Reference to an expansion rule by <name>."""

    # Name of referenced rule
    rule_name: str = ""


@dataclass
class ListReference(Expression):
    """Reference to a list by {name}."""

    list_name: str = ""
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    _slot_name: Optional[str] = None

    def __post_init__(self):
        if ":" in self.list_name:
            # list_name:slot_name
            self.list_name, self._slot_name = self.list_name.split(":", maxsplit=1)
        else:
            self._slot_name = self.list_name

    @property
    def slot_name(self) -> str:
        """Name of slot to put list value into."""
        assert self._slot_name is not None
        return self._slot_name


@dataclass
class Sentence(Sequence):
    """Sequence representing a complete sentence template."""

    text: Optional[str] = None
    pattern: Optional[re.Pattern] = None

    def compile(self, expansion_rules: Dict[str, "Sentence"]) -> None:
        if self.pattern is not None:
            # Already compiled
            return

        pattern_chunks: List[str] = []
        self._compile_expression(self, pattern_chunks, expansion_rules)

        pattern_str = "".join(pattern_chunks).replace(r"\ ", r"[ ]*")
        self.pattern = re.compile(f"^{pattern_str}$", re.IGNORECASE)

    def _compile_expression(
        self, exp: Expression, pattern_chunks: List[str], rules: Dict[str, "Sentence"]
    ):
        if isinstance(exp, TextChunk):
            # Literal text
            chunk: TextChunk = exp
            if chunk.text:
                escaped_text = re.escape(chunk.text)
                pattern_chunks.append(escaped_text)
        elif isinstance(exp, Sequence):
            # Linear sequence or alternative choices
            seq: Sequence = exp
            if seq.type == SequenceType.GROUP:
                # Linear sequence
                for item in seq.items:
                    self._compile_expression(item, pattern_chunks, rules)
            elif seq.type == SequenceType.ALTERNATIVE:
                # Alternative choices
                if seq.items:
                    pattern_chunks.append("(?:")
                    for item in seq.items:
                        self._compile_expression(item, pattern_chunks, rules)
                        pattern_chunks.append("|")
                    pattern_chunks[-1] = ")"
            else:
                raise ValueError(seq)
        elif isinstance(exp, ListReference):
            # Slot list
            pattern_chunks.append("(?:.+)")

        elif isinstance(exp, RuleReference):
            # Expansion rule
            rule_ref: RuleReference = exp
            if rule_ref.rule_name not in rules:
                raise ValueError(rule_ref)

            e_rule = rules[rule_ref.rule_name]
            self._compile_expression(e_rule, pattern_chunks, rules)
        else:
            raise ValueError(exp)
