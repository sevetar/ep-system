package com.schoolwork.epsys.model.approval;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName repairman_application
 */
@TableName(value ="repairman_application")
@Data
public class RepairmanApplication implements Serializable {
    private Integer id;

    private Integer userId;

    private String applyReason;

    private String qualificationProof;

    private Object status;

    private String approveComment;

    private Date approveTime;

    private Date createTime;

    private static final long serialVersionUID = 1L;
}