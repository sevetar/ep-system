USE devices;

CREATE TABLE IF NOT EXISTS work_order_knowledge_outbox (
  id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(128) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  order_id INT NOT NULL,
  order_version INT NOT NULL,
  trace_id VARCHAR(128) NOT NULL,
  payload JSON NOT NULL,
  publish_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  retry_count INT NOT NULL DEFAULT 0,
  next_retry_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_error VARCHAR(500) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_at DATETIME DEFAULT NULL,
  ingestion_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  chunk_count INT NOT NULL DEFAULT 0,
  quality_score INT NOT NULL DEFAULT 0,
  quality_issues JSON DEFAULT NULL,
  ingestion_error VARCHAR(1000) DEFAULT NULL,
  ingested_at DATETIME DEFAULT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_work_order_knowledge_event (event_id),
  KEY idx_work_order_knowledge_publish (publish_status, next_retry_at),
  KEY idx_work_order_knowledge_order (order_id, order_version),
  KEY idx_work_order_knowledge_ingestion (ingestion_status, updated_at)
) ENGINE=InnoDB;
