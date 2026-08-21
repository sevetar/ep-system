-- 工单完成信息：当前本地库已初始化时，请执行本增量脚本。
ALTER TABLE maintain_record
  ADD COLUMN repair_process VARCHAR(2000) NULL COMMENT '维修处理过程' AFTER description,
  ADD COLUMN solution VARCHAR(2000) NULL COMMENT '最终解决方案' AFTER repair_process;
