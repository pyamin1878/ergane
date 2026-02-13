"""Schema-based HTML extraction using selectolax."""

from datetime import datetime, timezone
from typing import Any, Type

from pydantic import BaseModel
from selectolax.parser import HTMLParser, Node

from ergane.schema.base import FieldConfig, SchemaConfig
from ergane.schema.coercion import CoercionError, TypeCoercer


class ExtractionError(Exception):
    """Raised when required field extraction fails."""

    pass


class SchemaExtractor:
    """Extracts data from HTML into typed Pydantic model instances."""

    def __init__(self, schema_config: SchemaConfig):
        """Initialize extractor with schema configuration.

        Args:
            schema_config: Parsed schema configuration from Pydantic model
        """
        self.schema_config = schema_config

    @classmethod
    def from_model(cls, model: Type[BaseModel]) -> "SchemaExtractor":
        """Create extractor from a Pydantic model class.

        Args:
            model: Pydantic model class with selector metadata

        Returns:
            SchemaExtractor instance
        """
        return cls(SchemaConfig.from_model(model))

    def extract(
        self,
        html: str,
        url: str,
        crawled_at: datetime | None = None,
    ) -> BaseModel:
        """Extract data from HTML into a Pydantic model instance.

        Args:
            html: HTML content to extract from
            url: URL of the page (for auto-populated url field)
            crawled_at: Timestamp (for auto-populated crawled_at field)

        Returns:
            Instance of the schema model with extracted data

        Raises:
            ExtractionError: If a required field cannot be extracted
        """
        if crawled_at is None:
            crawled_at = datetime.now(timezone.utc)

        tree = HTMLParser(html)
        data: dict[str, Any] = {}

        for field_name, field_config in self.schema_config.fields.items():
            if field_config.is_auto_populated:
                # Handle auto-populated fields
                if field_name == "url":
                    data[field_name] = url
                elif field_name == "crawled_at":
                    data[field_name] = crawled_at
            elif field_config.selector:
                # Extract using CSS selector
                value = self._extract_field(tree, field_config, url)
                data[field_name] = value

        return self.schema_config.model(**data)

    def _extract_field(
        self, tree: HTMLParser, field_config: FieldConfig, url: str = ""
    ) -> Any:
        """Extract a single field value from the HTML tree.

        Args:
            tree: Parsed HTML tree
            field_config: Configuration for the field to extract
            url: Source URL for error context

        Returns:
            Extracted and coerced value

        Raises:
            ExtractionError: If required field extraction fails
        """
        if not field_config.selector:
            return field_config.default if field_config.default is not ... else None

        nodes = tree.css(field_config.selector)

        if not nodes:
            return self._handle_no_match(field_config, url)

        if field_config.is_nested_model:
            return self._extract_nested(nodes, field_config)

        if field_config.is_list:
            return self._extract_list(nodes, field_config)
        else:
            return self._extract_single(nodes[0], field_config, url)

    def _handle_no_match(self, field_config: FieldConfig, url: str = "") -> Any:
        """Handle case where selector matches no elements.

        Args:
            field_config: Configuration for the field
            url: Source URL for error context

        Returns:
            Default value for optional/list fields

        Raises:
            ExtractionError: If field is required and has no default
        """
        # List fields default to empty list
        if field_config.is_list:
            return []
        # Field has explicit default
        if field_config.default is not ...:
            return field_config.default
        # Optional field defaults to None
        if field_config.is_optional:
            return None
        # Required field with no match - raise error
        url_context = f" (url: {url})" if url else ""
        raise ExtractionError(
            f"Required field '{field_config.name}' not found with "
            f"selector: {field_config.selector}{url_context}"
        )

    def _extract_single(
        self, node: Node, field_config: FieldConfig, url: str = ""
    ) -> Any:
        """Extract value from a single node.

        Args:
            node: HTML node to extract from
            field_config: Configuration for the field
            url: Source URL for error context

        Returns:
            Extracted and coerced value
        """
        raw_value = self._get_node_value(node, field_config.attr)
        if raw_value is None:
            return self._handle_no_match(field_config, url)

        try:
            return TypeCoercer.coerce(
                raw_value, field_config.python_type, field_config.coerce
            )
        except CoercionError as e:
            if field_config.is_optional or field_config.default is not ...:
                return (
                    field_config.default
                    if field_config.default is not ...
                    else None
                )
            url_context = f" (url: {url})" if url else ""
            raise ExtractionError(
                f"Failed to coerce field '{field_config.name}': {e}{url_context}"
            ) from e

    def _extract_list(self, nodes: list[Node], field_config: FieldConfig) -> list[Any]:
        """Extract list of values from multiple nodes.

        Args:
            nodes: HTML nodes to extract from
            field_config: Configuration for the field

        Returns:
            List of extracted and coerced values
        """
        values = []
        for node in nodes:
            raw_value = self._get_node_value(node, field_config.attr)
            if raw_value is not None:
                try:
                    coerced = TypeCoercer.coerce(
                        raw_value, field_config.python_type, field_config.coerce
                    )
                    values.append(coerced)
                except CoercionError:
                    # Skip values that fail coercion in lists
                    pass
        return values

    def _extract_nested(
        self, nodes: list[Node], field_config: FieldConfig
    ) -> BaseModel | list[BaseModel] | None:
        """Extract nested Pydantic model(s) from nodes.

        Args:
            nodes: HTML nodes containing nested model data
            field_config: Configuration for the nested field

        Returns:
            Single nested model instance or list of instances
        """
        if field_config.inner_type is None:
            return None

        nested_schema = SchemaConfig.from_model(field_config.inner_type)

        if field_config.is_list:
            results = []
            for node in nodes:
                try:
                    item = self._extract_nested_item(node, nested_schema)
                    results.append(item)
                except ExtractionError:
                    # Skip items that fail extraction in lists
                    pass
            return results
        else:
            try:
                return self._extract_nested_item(nodes[0], nested_schema)
            except ExtractionError:
                return self._handle_no_match(field_config)

    def _extract_nested_item(
        self, node: Node, schema: SchemaConfig
    ) -> BaseModel:
        """Extract a single nested model from a node.

        Args:
            node: HTML node containing the nested model data
            schema: Schema configuration for the nested model

        Returns:
            Instance of the nested model
        """
        data: dict[str, Any] = {}

        for field_name, field_config in schema.fields.items():
            if field_config.selector:
                # Find matching nodes within this parent node
                inner_nodes = node.css(field_config.selector)
                if not inner_nodes:
                    value = self._handle_no_match(field_config)
                elif field_config.is_list:
                    value = self._extract_list(inner_nodes, field_config)
                else:
                    value = self._extract_single(inner_nodes[0], field_config)
                data[field_name] = value

        return schema.model(**data)

    def _get_node_value(self, node: Node, attr: str | None) -> str | None:
        """Get value from a node (text content or attribute).

        Args:
            node: HTML node
            attr: Attribute name to extract, or None for text content

        Returns:
            Extracted string value or None
        """
        if attr:
            value = node.attributes.get(attr)
            return value.strip() if value else None
        else:
            text = node.text(strip=True)
            return text if text else None
