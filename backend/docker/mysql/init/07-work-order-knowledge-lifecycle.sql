USE devices;

ALTER TABLE maintain_record
  ADD COLUMN root_cause VARCHAR(2000) NULL COMMENT '确认或推测的故障根因' AFTER solution,
  ADD COLUMN verification_result VARCHAR(2000) NULL COMMENT '修复后的验证结果' AFTER root_cause,
  ADD COLUMN replaced_parts VARCHAR(1000) NULL COMMENT '更换部件' AFTER verification_result,
  ADD COLUMN knowledge_tags VARCHAR(1000) NULL COMMENT '知识标签，逗号分隔' AFTER replaced_parts;

ALTER TABLE work_order_knowledge_outbox
  ADD COLUMN ingestion_status VARCHAR(16) NOT NULL DEFAULT 'PENDING' AFTER published_at,
  ADD COLUMN chunk_count INT NOT NULL DEFAULT 0 AFTER ingestion_status,
  ADD COLUMN quality_score INT NOT NULL DEFAULT 0 AFTER chunk_count,
  ADD COLUMN quality_issues JSON NULL AFTER quality_score,
  ADD COLUMN ingestion_error VARCHAR(1000) NULL AFTER quality_issues,
  ADD COLUMN ingested_at DATETIME NULL AFTER ingestion_error,
  ADD KEY idx_work_order_knowledge_ingestion (ingestion_status, updated_at);
