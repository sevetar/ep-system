package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * 维修员的派单运行画像。该表只保存派单硬门禁字段，账户身份仍由 ACL 服务拥有。
 */
@Data
@TableName("repairman_dispatch_profile")
public class RepairmanDispatchProfile implements Serializable {

    @TableId
    private Integer workerId;

    private String tenantId;

    private String regionCode;

    private String shiftStatus;

    private Boolean available;

    private Integer capacity;

    private Boolean active;

    private Date updatedAt;

    private static final long serialVersionUID = 1L;
}
