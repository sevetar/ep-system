USE devices;

ALTER TABLE maintain_record
  ADD COLUMN claim_deadline DATETIME NULL COMMENT '审批通过后的自主抢单截止时间' AFTER approval_time,
  ADD KEY idx_maintain_claim_timeout (status, miantain_id, claim_deadline);

CREATE TABLE IF NOT EXISTS dispatch_event_outbox (
  id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(128) NOT NULL,
  dispatch_id VARCHAR(128) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL,
  order_id INT NOT NULL,
  trace_id VARCHAR(128) NOT NULL,
  trigger_type VARCHAR(32) NOT NULL,
  order_version INT NOT NULL,
  payload JSON NOT NULL,
  publish_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  retry_count INT NOT NULL DEFAULT 0,
  next_retry_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_error VARCHAR(500) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_at DATETIME DEFAULT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_dispatch_outbox_event (event_id),
  UNIQUE KEY uk_dispatch_outbox_dispatch (dispatch_id),
  KEY idx_dispatch_outbox_publish (publish_status, next_retry_at),
  KEY idx_dispatch_outbox_order (order_id)
) ENGINE=InnoDB;

USE users;

INSERT INTO permissions (id, permission_name, permission_code, permission_desc)
VALUES (1001, '手动触发自动派单', 'dispatch:auto:trigger', '允许管理员为待领取工单触发 Agent 自动派单')
ON DUPLICATE KEY UPDATE permission_name = VALUES(permission_name), permission_desc = VALUES(permission_desc);

INSERT IGNORE INTO roletopermission (role_id, permission_id)
SELECT id, 1001 FROM roles WHERE role_name = 'admin';
