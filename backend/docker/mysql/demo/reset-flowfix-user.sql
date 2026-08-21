-- 仅重置固定本地账号 flowfix_user 的维修员申请演示状态。
-- 不删除用户，不影响其他账号；只允许在个人本地开发库执行。
USE users;

DELETE FROM repairman_application WHERE user_id = 90002;
DELETE FROM usertorole WHERE user_id = 90002 AND role_id = 3;

INSERT INTO usertorole (user_id, role_id)
VALUES (90002, 2)
ON DUPLICATE KEY UPDATE role_id = VALUES(role_id);
