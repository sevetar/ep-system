USE devices;

ALTER TABLE maintain_record
  ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT 'default' AFTER device_id,
  ADD COLUMN priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL' AFTER maintenance_type;

ALTER TABLE maintain_order_claim
  MODIFY COLUMN request_id VARCHAR(300) NOT NULL;

CREATE TABLE IF NOT EXISTS repairman_dispatch_profile (
  worker_id INT NOT NULL,
  tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
  region_code VARCHAR(64) NOT NULL,
  shift_status VARCHAR(16) NOT NULL DEFAULT 'OFF_DUTY',
  available TINYINT(1) NOT NULL DEFAULT 0,
  capacity INT NOT NULL DEFAULT 1,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (worker_id),
  KEY idx_dispatch_profile_candidate (tenant_id, active, available, shift_status, region_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS repairman_dispatch_skill (
  worker_id INT NOT NULL,
  skill_code VARCHAR(64) NOT NULL,
  PRIMARY KEY (worker_id, skill_code),
  KEY idx_dispatch_skill_code (skill_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS dispatch_assignment (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id VARCHAR(64) NOT NULL,
  order_id INT NOT NULL,
  worker_id INT NOT NULL,
  idempotency_key VARCHAR(300) NOT NULL,
  event_id VARCHAR(128) NOT NULL,
  dispatch_id VARCHAR(128) NOT NULL,
  trace_id VARCHAR(64) NOT NULL,
  expected_version INT NOT NULL,
  result_version INT DEFAULT NULL,
  command_hash CHAR(64) NOT NULL,
  receipt_status VARCHAR(32) NOT NULL,
  reason_code VARCHAR(64) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_dispatch_assignment_idempotency (idempotency_key),
  UNIQUE KEY uk_dispatch_assignment_dispatch (dispatch_id),
  KEY idx_dispatch_assignment_order (order_id),
  KEY idx_dispatch_assignment_event (event_id)
) ENGINE=InnoDB;
