package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

@Data
@TableName("device_binding_command")
public class DeviceBindingCommand implements Serializable {
    private Long id;
    private String requestId;
    private String eventId;
    private String eventType;
    private Integer userId;
    private Integer deviceId;
    private String resultStatus;
    private String reasonCode;
    private Date createdAt;
    private Date updatedAt;
}
