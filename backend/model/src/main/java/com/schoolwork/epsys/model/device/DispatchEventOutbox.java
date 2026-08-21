package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * 自动派单事件 Outbox。业务事务只写本表，后台发布器负责可靠投递 RabbitMQ。
 */
@Data
@TableName("dispatch_event_outbox")
public class DispatchEventOutbox implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String eventId;
    private String dispatchId;
    private String tenantId;
    private Integer orderId;
    private String traceId;
    private String triggerType;
    private Integer orderVersion;
    private String payload;
    private String publishStatus;
    private Integer retryCount;
    private Date nextRetryAt;
    private String lastError;
    private Date createdAt;
    private Date publishedAt;
    private Date updatedAt;

    private static final long serialVersionUID = 1L;
}
