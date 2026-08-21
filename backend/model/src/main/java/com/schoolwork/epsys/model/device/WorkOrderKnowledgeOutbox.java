package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/** 工单完成知识事件 Outbox；业务事务只落库，后台发布器负责可靠投递。 */
@Data
@TableName("work_order_knowledge_outbox")
public class WorkOrderKnowledgeOutbox implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String eventId;
    private String tenantId;
    private Integer orderId;
    private Integer orderVersion;
    private String traceId;
    private String payload;
    private String publishStatus;
    private Integer retryCount;
    private Date nextRetryAt;
    private String lastError;
    private Date createdAt;
    private Date publishedAt;
    private String ingestionStatus;
    private Integer chunkCount;
    private Integer qualityScore;
    private String qualityIssues;
    private String ingestionError;
    private Date ingestedAt;
    private Date updatedAt;

    private static final long serialVersionUID = 1L;
}
