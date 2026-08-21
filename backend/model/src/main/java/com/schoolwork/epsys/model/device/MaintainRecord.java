package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;

import com.baomidou.mybatisplus.annotation.Version;
import lombok.Data;

/**
 * @TableName maintain_record
 */
@TableName(value ="maintain_record")
@Data
public class MaintainRecord implements Serializable {
    private Integer id;

    private Integer deviceId;

    private String tenantId;

    private Object maintenanceType;

    private String priority;

    private Date startTime;

    private Date endTime;

    private Integer operatorId;

    private String description;

    private String repairProcess;

    private String solution;

    private String rootCause;

    private String verificationResult;

    private String replacedParts;

    private String knowledgeTags;

    private Object status;

    private Integer approvalId;

    private Date approvalTime;

    /** 审批通过后的自主抢单截止时间；到期仍无人领取时触发自动派单。 */
    private Date claimDeadline;

    private Integer miantainId;

    @Version
    private Integer version;

    private static final long serialVersionUID = 1L;
}
