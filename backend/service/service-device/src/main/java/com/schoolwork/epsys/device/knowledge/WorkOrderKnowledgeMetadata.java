package com.schoolwork.epsys.device.knowledge;

/** 从设备关系表读取的可信知识检索元数据。 */
public record WorkOrderKnowledgeMetadata(String deviceCategory, String deviceModel) {

    public static WorkOrderKnowledgeMetadata unknown() {
        return new WorkOrderKnowledgeMetadata("", "");
    }
}
