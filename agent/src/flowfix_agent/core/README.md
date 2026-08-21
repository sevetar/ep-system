# Core

最小共享内核：配置、通用错误、可信 RequestContext、trace、clock、ID 和少量真正跨模块合同。

RequestContext 应承载 tenant、user/thread、event、permissions、deadline、预算和 trace；权限必须来自认证上下文，不能信任请求正文或模型输出。

禁止把 Tool Registry、Memory Service、业务模型、外部 Client 或通用 `utils.py` 塞入 Core。它们应属于各自限界上下文并由 Bootstrap 装配。
