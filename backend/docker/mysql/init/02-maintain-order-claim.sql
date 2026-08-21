USE devices;

CREATE TABLE IF NOT EXISTS maintain_order_claim (
  id BIGINT NOT NULL AUTO_INCREMENT,
  order_id INT NOT NULL,
  repairman_id INT NOT NULL,
  request_id VARCHAR(64) NOT NULL,
  claimed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_maintain_order_claim_order (order_id),
  UNIQUE KEY uk_maintain_order_claim_request (request_id),
  KEY idx_maintain_order_claim_repairman (repairman_id)
) ENGINE=InnoDB;
