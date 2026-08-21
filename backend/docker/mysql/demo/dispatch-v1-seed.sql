-- 本地功能演示与 M5 联调固定数据。仅用于开发环境，可重复执行。
USE users;

INSERT INTO `user` (id, username, password, phone, status, create_time)
VALUES
  (90001, 'flowfix_admin', 'FlowFix123', '13900000001', 1, CURRENT_TIMESTAMP),
  (90002, 'flowfix_user', 'FlowFix123', '13900000002', 1, CURRENT_TIMESTAMP),
  (91001, 'flowfix_worker_a', 'FlowFix123', '13900000011', 1, CURRENT_TIMESTAMP),
  (91002, 'flowfix_worker_b', 'FlowFix123', '13900000012', 1, CURRENT_TIMESTAMP),
  (91003, 'flowfix_worker_c', 'FlowFix123', '13900000013', 1, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE
  username = VALUES(username), password = VALUES(password),
  phone = VALUES(phone), status = VALUES(status);

INSERT INTO usertorole (user_id, role_id)
VALUES
  (90001, 1),
  (90002, 2),
  (91001, 3), (91002, 3), (91003, 3)
ON DUPLICATE KEY UPDATE role_id = VALUES(role_id);

USE devices;

INSERT INTO devicecategory (id, category_name, description)
VALUES (90001, 'DISPATCH_DEMO', 'M5 联调固定设备分类')
ON DUPLICATE KEY UPDATE description = VALUES(description);

INSERT INTO devicemodel (id, category_id, model_name, description)
VALUES (90001, 90001, 'DISPATCH_DEMO_MODEL', 'M5 联调固定设备型号')
ON DUPLICATE KEY UPDATE description = VALUES(description);

INSERT INTO deviceinstance (id, model_id, serial_number, status, location)
VALUES
  (90001, 90001, 'DISPATCH-DEMO-001', '待维修', 'CAMPUS_EAST'),
  (90002, 90001, 'DISPATCH-DEMO-002', '维护中', 'CAMPUS_EAST'),
  (90003, 90001, 'DISPATCH-DEMO-003', '待维修', 'CAMPUS_EAST')
ON DUPLICATE KEY UPDATE location = VALUES(location);

INSERT INTO maintain_record
  (id, device_id, tenant_id, maintenance_type, priority, start_time, description, status, miantain_id, version)
VALUES
  (92001, 90001, 'default', 'ELECTRICAL', 'NORMAL', CURRENT_TIMESTAMP,
   'M5 自动派单联调工单', '待领取', NULL, 0),
  (92002, 90002, 'default', 'ELECTRICAL', 'NORMAL', CURRENT_TIMESTAMP,
   '用于形成 Worker B 真实负载的在途工单', '维护中', 91002, 0),
  (92003, 90003, 'default', 'ELECTRICAL', 'NORMAL', CURRENT_TIMESTAMP,
   'M5 冲突与硬门禁联调工单', '待领取', NULL, 0)
ON DUPLICATE KEY UPDATE
  tenant_id = VALUES(tenant_id), maintenance_type = VALUES(maintenance_type),
  priority = VALUES(priority), description = VALUES(description);

INSERT INTO repairman_dispatch_profile
  (worker_id, tenant_id, region_code, shift_status, available, capacity, active)
VALUES
  (91001, 'default', 'CAMPUS_EAST', 'ON_DUTY', 1, 3, 1),
  (91002, 'default', 'CAMPUS_EAST', 'ON_DUTY', 1, 3, 1),
  (91003, 'default', 'CAMPUS_WEST', 'ON_DUTY', 1, 3, 1)
ON DUPLICATE KEY UPDATE
  tenant_id = VALUES(tenant_id), region_code = VALUES(region_code),
  shift_status = VALUES(shift_status), available = VALUES(available),
  capacity = VALUES(capacity), active = VALUES(active);

INSERT INTO repairman_dispatch_skill (worker_id, skill_code)
VALUES
  (91001, 'ELECTRICAL'),
  (91002, 'ELECTRICAL'),
  (91003, 'HVAC')
ON DUPLICATE KEY UPDATE skill_code = VALUES(skill_code);
