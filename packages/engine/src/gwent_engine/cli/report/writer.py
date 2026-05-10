from __future__ import annotations

from pathlib import Path
from typing import ClassVar, final

from jinja2 import Environment, PackageLoader, select_autoescape

from gwent_engine.cli.report.format import HTMLFormatter


@final
class ReportWriter:
    _template_env: ClassVar[Environment] = Environment(
        loader=PackageLoader("gwent_engine", "cli/templates"),
        autoescape=select_autoescape(("html", "xml")),
    )

    def __init__(self, *, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir or Path(".output")

    def render(
        self,
        *,
        template_name: str,
        title: str,
        context: dict[str, object],
        generated_at: str | None = None,
    ) -> str:
        template = self._template_env.get_template(template_name)
        return template.render(
            title=title,
            generated_at=generated_at or HTMLFormatter.generated_at(),
            **context,
        )

    def write(
        self,
        *,
        filename: str,
        template_name: str,
        title: str,
        context: dict[str, object],
        generated_at: str | None = None,
    ) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._output_dir / filename
        _ = report_path.write_text(
            self.render(
                template_name=template_name,
                title=title,
                context=context,
                generated_at=generated_at,
            ),
            encoding="utf-8",
        )
        return report_path
