"""岗位库向业务工作台交接的有界上下文模型。"""

from pydantic import BaseModel, Field


class JobContextSnapshot(BaseModel):
    """保存来源身份与用户实际编辑内容的岗位上下文快照。"""

    source_job_id: int = Field(..., gt=0)
    source_platform: str = Field(default="", max_length=50)
    source_url: str = Field(default="", max_length=2000)
    company_name: str = Field(default="", max_length=200)
    company_size_text: str = Field(default="", max_length=100)
    job_title: str = Field(default="", max_length=200)
    job_description: str = Field(default="", max_length=100_000)
    salary_text: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=100)
    imported_at: str = Field(default="", max_length=100)
