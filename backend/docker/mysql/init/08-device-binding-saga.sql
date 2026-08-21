USE users;

ALTER TABLE devicetousers
  ADD COLUMN binding_status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' AFTER device_id,
  ADD COLUMN request_id VARCHAR(128) NULL AFTER binding_status,
  ADD COLUMN failure_reason VARCHAR(128) NULL AFTER request_id,
  ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER failure_reason,
  DROP INDEX idx_devicetousers_device,
  ADD UNIQUE KEY uk_devicetousers_device (device_id),
  ADD UNIQUE KEY uk_devicetousers_request (request_id);

CREATE TABLE device_binding_outbox (
  id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(128) NOT NULL,
  request_id VARCHAR(128) NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  user_id INT NOT NULL,
  device_id INT NOT NULL,
  payload JSON NOT NULL,
  publish_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  retry_count INT NOT NULL DEFAULT 0,
  next_retry_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_error VARCHAR(500) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_at DATETIME DEFAULT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_device_binding_outbox_event (event_id),
  UNIQUE KEY uk_device_binding_outbox_request (request_id),
  KEY idx_device_binding_outbox_publish (publish_status, next_retry_at)
) ENGINE=InnoDB;

USE devices;

CREATE TABLE device_binding_command (
  id BIGINT NOT NULL AUTO_INCREMENT,
  request_id VARCHAR(128) NOT NULL,
  event_id VARCHAR(128) NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  user_id INT NOT NULL,
  device_id INT NOT NULL,
  result_status VARCHAR(16) NOT NULL,
  reason_code VARCHAR(64) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_device_binding_command_request (request_id),
  UNIQUE KEY uk_device_binding_command_event (event_id),
  KEY idx_device_binding_command_device (device_id)
) ENGINE=InnoDB;

CREATE TABLE device_binding_result_outbox (
  id BIGINT NOT NULL AUTO_INCREMENT,
  event_id VARCHAR(128) NOT NULL,
  request_id VARCHAR(128) NOT NULL,
  event_type VARCHAR(32) NOT NULL,
  user_id INT NOT NULL,
  device_id INT NOT NULL,
  payload JSON NOT NULL,
  publish_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  retry_count INT NOT NULL DEFAULT 0,
  next_retry_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_error VARCHAR(500) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  published_at DATETIME DEFAULT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_device_binding_result_event (event_id),
  UNIQUE KEY uk_device_binding_result_request (request_id),
  KEY idx_device_binding_result_publish (publish_status, next_retry_at)
) ENGINE=InnoDB;
