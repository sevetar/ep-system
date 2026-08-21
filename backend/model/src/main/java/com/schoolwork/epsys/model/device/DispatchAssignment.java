package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * Agent 派单命令的持久化审计记录，也是响应丢失后的幂等与 outcome 查询依据。
 */
@Data
@TableName("dispatch_assignment")
public class DispatchAssignment implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String tenantId;
    private Integer orderId;
    private Integer workerId;
    private String idempotencyKey;
    private String eventId;
    private String dispatchId;
    private String traceId;
    private Integer expectedVersion;
    private Integer resultVersion;
    private String commandHash;
    private String receiptStatus;
    private String reasonCode;
    private Date createdAt;
    private Date updatedAt;

    private static final long serialVersionUID = 1L;
}
