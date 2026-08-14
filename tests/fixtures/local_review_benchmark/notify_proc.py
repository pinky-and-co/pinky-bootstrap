"""Synthetic Snowpark stored procedure — benchmark fixture for local/cloud code review.

Public-safe equivalent of a real internal notification procedure: same *shape* and same
*defect classes* (see review_brief.md / the benchmark oracle), zero proprietary content.
Used to score how well a model reviews data-engineering Snowpark code. Not production code.
"""

import base64
import logging

import snowflake.snowpark as snowpark
from snowflake import telemetry
from snowflake.snowpark.files import SnowflakeFile
from snowflake.snowpark.functions import (
    call_udf,
    get,
    lit,
    object_construct,
    to_varchar,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================
THEMES: dict = {
    "default": {
        "header_bg": "#2440ff",
        "footer_bg": "#f4f4f4",
        "greeting_color": "#0016a3",
        "signature_color": "#06187b",
        "footer_color": "#666",
        "header_font": "Arial Black",
        "header_size": "26px",
        "subheader_size": "20px",
        "logo_url": "https://assets.example.com/logo/base/logo.png?s=xs",
        "logo_width": "60",
        "signature": "Notifications Team",
    },
    "alt": {
        "header_bg": "#5eb991",
        "footer_bg": "#f4f4f4",
        "greeting_color": "#327156",
        "signature_color": "#000000",
        "footer_color": "#666",
        "header_font": "Arial Black",
        "header_size": "26px",
        "subheader_size": "20px",
        "logo_url": "https://assets.example.com/alt/base/logo.png?s=xs",
        "logo_width": "120",
        "signature": "Notifications Team",
    },
}

LANGS: dict = {
    "fr": {
        "greeting_begin": "Bonjour",
        "greeting_end": "Cordialement",
        "footer": "Ceci est une notification automatique. Merci de ne pas y répondre.",
    },
    "en": {
        "greeting_begin": "Hi",
        "greeting_end": "Best regards",
        "footer": "This is an automated notification. Please do not reply.",
    },
}

DEFAULT_THEME: dict = THEMES["default"]
DEFAULT_LANG: dict = LANGS["fr"]


def generate_html(
    header: str,
    subheader: str,
    body: str,
    theme: dict | None = None,
    lang: dict | None = None,
) -> str:
    """Render the notification HTML from a header, subheader and HTML body."""
    t = {**DEFAULT_THEME, **(theme or {})}
    tx = {**DEFAULT_LANG, **(lang or {})}
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body><table width="100%"><tr><td align="center"><table width="840">
<tr><td bgcolor="{t["header_bg"]}" align="center"><div style="color:#fff;font-family:{t["header_font"]};font-size:{t["header_size"]}">{header}</div>
<div style="color:#fff;font-size:{t["subheader_size"]}">{subheader}</div></td></tr>
<tr><td><p style="color:{t["greeting_color"]};font-weight:bold">{tx["greeting_begin"]},</p>
{body}
<p>{tx["greeting_end"]},<br><span style="color:{t["signature_color"]}">{t["signature"]}</span></p>
<img src="{t["logo_url"]}" width="{t["logo_width"]}" alt="logo"></td></tr>
<tr><td bgcolor="{t["footer_bg"]}" align="center"><p style="font-size:11px;color:{t["footer_color"]}">{tx["footer"]}</p></td></tr>
</table></td></tr></table></body></html>'''


def main(session: snowpark.Session, args: dict) -> dict:
    """Send a notification via an external API UDF, with a SYSTEM$SEND_EMAIL fallback.

    args keys: to_addresses, subject, header, subheader, body, attachments,
    theme ("default"|"alt"|{"name": ..., overrides}), lang ({"locale": "fr"|"en", overrides}).
    Returns {"status": "SUCCEEDED"|"FAILED", "idMessage": str}.
    """
    to_addresses: list = args.get("to_addresses", [])
    subject: str = args.get("subject", "")
    header: str = args.get("header", "")
    subheader: str = args.get("subheader", "")
    body: str = args.get("body", "")
    attachments: list = args.get("attachments", [])

    theme_arg = args.get("theme", {})
    theme_name = (
        theme_arg if isinstance(theme_arg, str) else theme_arg.get("name", "default")
    )
    theme_overrides = (
        {}
        if isinstance(theme_arg, str)
        else {k: v for k, v in theme_arg.items() if k != "name"}
    )
    theme: dict = {**THEMES.get(theme_name, THEMES["default"]), **theme_overrides}

    lang_arg: dict = args.get("lang", {})
    locale: str = lang_arg.get("locale", "fr")
    lang: dict = {
        **LANGS.get(locale, LANGS["fr"]),
        **{k: v for k, v in lang_arg.items() if k != "locale"},
    }

    html_body = generate_html(
        header=header, subheader=subheader, body=body, theme=theme, lang=lang
    )

    # Build attachments (base64-encoded from a stage)
    v_attachments: list = []
    for attachment in attachments:
        v_stage = "@" + attachment.split("/")[0]
        v_relative_path = "/".join(attachment.split("/")[1:])
        v_filename = attachment.split("/")[-1]
        v_extension = v_filename.split(".")[-1]

        df = session.sql(
            f"SELECT BUILD_SCOPED_FILE_URL('{v_stage}', '{v_relative_path}') AS FILE_URL"
        )

        for row in df.to_local_iterator():
            with SnowflakeFile.open(
                str(row["FILE_URL"]), "rb", encoding="utf-8"
            ) as binary_file:
                binary_file_data = bytes(binary_file.read())
                base64_output = base64.b64encode(binary_file_data).decode("utf-8")
                v_attachments.append(
                    {
                        "content": base64_output,
                        "extension": v_extension,
                        "type": "ToUploadFileDto",
                        "name": v_filename,
                    }
                )

    # Primary send via external notification API UDF
    id_message: str | None = None
    try:
        df = session.create_dataframe(
            [[html_body, to_addresses, subject, v_attachments]],
            schema=['"message"', '"recipients"', '"subject"', '"attachments"'],
        )
        id_message = str(
            df.select(
                to_varchar(
                    get(
                        call_udf("APP.EXTERNAL_NOTIFY_API", object_construct("*")),
                        lit("id"),
                    )
                )
            ).collect()[0][0]
        )
    except Exception as e:
        logger.error(f"EXTERNAL_NOTIFY_API failed: {e}")

    status = "FAILED" if id_message is None else "SUCCEEDED"

    # Fallback when the primary failed, or when the subject is flagged
    if id_message is None or "FAILED" in subject:
        try:
            session.call(
                "SYSTEM$SEND_EMAIL",
                "NOTIFY_INTEGRATION",
                "ops-fallback@example.com",
                subject,
                html_body,
                "text/html",
            )
        except Exception as e:
            logger.error(f"SYSTEM$SEND_EMAIL failed: {e}")

    v_result = {
        "status": status,
        "idMessage": id_message if id_message is not None else "SERVICE_UNAVAILABLE",
    }

    if status == "FAILED":
        telemetry.add_event(
            "notify_failed",
            {
                "subject": subject,
                "recipients": str(to_addresses),
                "attachments_count": len(v_attachments),
            },
        )

    return v_result
