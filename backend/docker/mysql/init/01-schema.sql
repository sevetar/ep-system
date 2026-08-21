CREATE DATABASE IF NOT EXISTS users
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS devices
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE users;

CREATE TABLE IF NOT EXISTS `user` (
  id INT NOT NULL AUTO_INCREMENT,
  username VARCHAR(64) NOT NULL,
  password VARCHAR(255) NOT NULL,
  phone VARCHAR(32) DEFAULT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  avatar VARCHAR(512) DEFAULT NULL,
  last_time DATETIME DEFAULT NULL,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_username (username)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS roles (
  id INT NOT NULL AUTO_INCREMENT,
  role_name VARCHAR(64) NOT NULL,
  role_desc VARCHAR(255) DEFAULT NULL,
  status TINYINT NOT NULL DEFAULT 1,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_roles_name (role_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS permissions (
  id INT NOT NULL AUTO_INCREMENT,
  permission_name VARCHAR(64) NOT NULL,
  permission_code VARCHAR(128) NOT NULL,
  permission_desc VARCHAR(255) DEFAULT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_permissions_code (permission_code)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS usertorole (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  role_id INT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_usertorole (user_id, role_id),
  KEY idx_usertorole_role (role_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS roletopermission (
  id INT NOT NULL AUTO_INCREMENT,
  role_id INT NOT NULL,
  permission_id INT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_roletopermission (role_id, permission_id),
  KEY idx_roletopermission_permission (permission_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS devicetousers (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  device_id INT NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_devicetousers (user_id, device_id),
  KEY idx_devicetousers_device (device_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS repairman_application (
  id INT NOT NULL AUTO_INCREMENT,
  user_id INT NOT NULL,
  apply_reason VARCHAR(1000) DEFAULT NULL,
  qualification_proof VARCHAR(512) DEFAULT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  approve_comment VARCHAR(1000) DEFAULT NULL,
  approve_time DATETIME DEFAULT NULL,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_repairman_application_user (user_id),
  KEY idx_repairman_application_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_message (
  id INT NOT NULL AUTO_INCREMENT,
  sender_id INT NOT NULL,
  receiver_id INT NOT NULL,
  content TEXT NOT NULL,
  is_read TINYINT NOT NULL DEFAULT 0,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_chat_participants_time (sender_id, receiver_id, create_time),
  KEY idx_chat_receiver_read (receiver_id, is_read)
) ENGINE=InnoDB;

INSERT INTO roles (id, role_name, role_desc, status)
VALUES
  (1, 'admin', '系统管理员', 1),
  (2, 'user', '普通用户', 1),
  (3, 'repairman', '维修人员', 1)
ON DUPLICATE KEY UPDATE role_name = VALUES(role_name);

USE devices;

CREATE TABLE IF NOT EXISTS devicecategory (
  id INT NOT NULL AUTO_INCREMENT,
  category_name VARCHAR(128) NOT NULL,
  description VARCHAR(1000) DEFAULT NULL,
  create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_devicecategory_name (category_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS devicemodel (
  id INT NOT NULL AUTO_INCREMENT,
  category_id INT NOT NULL,
  model_name VARCHAR(128) NOT NULL,
  description VARCHAR(1000) DEFAULT NULL,
  image VARCHAR(512) DEFAULT NULL,
  create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_devicemodel_category (category_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS deviceinstance (
  id INT NOT NULL AUTO_INCREMENT,
  model_id INT NOT NULL,
  serial_number VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT '闲置',
  create_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  location VARCHAR(255) DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_deviceinstance_serial (serial_number),
  KEY idx_deviceinstance_model (model_id),
  KEY idx_deviceinstance_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS maintain_record (
  id INT NOT NULL AUTO_INCREMENT,
  device_id INT NOT NULL,
  maintenance_type VARCHAR(64) DEFAULT NULL,
  start_time DATETIME DEFAULT NULL,
  end_time DATETIME DEFAULT NULL,
  operator_id INT DEFAULT NULL,
  description VARCHAR(1000) DEFAULT NULL,
  repair_process VARCHAR(2000) DEFAULT NULL,
  solution VARCHAR(2000) DEFAULT NULL,
  root_cause VARCHAR(2000) DEFAULT NULL,
  verification_result VARCHAR(2000) DEFAULT NULL,
  replaced_parts VARCHAR(1000) DEFAULT NULL,
  knowledge_tags VARCHAR(1000) DEFAULT NULL,
  status VARCHAR(32) NOT NULL DEFAULT '待审批',
  approval_id INT DEFAULT NULL,
  approval_time DATETIME DEFAULT NULL,
  miantain_id INT DEFAULT NULL,
  version INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_maintain_device (device_id),
  KEY idx_maintain_operator (operator_id),
  KEY idx_maintain_repairman (miantain_id),
  KEY idx_maintain_status (status)
) ENGINE=InnoDB;
