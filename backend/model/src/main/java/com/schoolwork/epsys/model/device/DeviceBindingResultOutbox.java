package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

@Data
@TableName("device_binding_result_outbox")
public class DeviceBindingResultOutbox implements Serializable {
    private Long id;
    private String eventId;
    private String requestId;
    private String eventType;
    private Integer userId;
    private Integer deviceId;
    private String payload;
    private String publishStatus;
    private Integer retryCount;
    private Date nextRetryAt;
    private String lastError;
    private Date createdAt;
    private Date publishedAt;
    private Date updatedAt;
}
