from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    wecom_token: str = ""
    wecom_encoding_aes_key: str = ""
    wecom_corp_id: str = ""
    wecom_kf_secret: str = ""
    wecom_api_base: str = "https://qyapi.weixin.qq.com/cgi-bin"
    zhipu_api_key: str = ""
    zhipu_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-5.3-flash"
    bot_name: str = "我的 Agent"
    bot_owner_name: str = "本人"
    knowledge_base_dir: str = "knowledge/approved"
    knowledge_max_chars: int = 6000
    rag_api_url: str = ""
    rag_api_token: str = ""
    handoff_threshold: float = 0.62
    wecom_state_db: str = "data/wecom_state.db"


settings = Settings()
