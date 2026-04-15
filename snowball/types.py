from typing import Literal

Status = Literal["approved", "maybe", "rejected", "unreviewed"]
Source = Literal["arxiv", "semantic_scholar", "openalex"]
Direction = Literal["references", "citations"]
ReviewedBy = Literal["auto", "user"]
