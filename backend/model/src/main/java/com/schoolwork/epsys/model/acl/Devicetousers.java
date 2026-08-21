package com.schoolwork.epsys.model.acl;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName devicetousers
 */
@TableName(value ="devicetousers")
@Data
public class Devicetousers implements Serializable {
    private Integer id;

    private Integer userId;

    private Integer deviceId;

    private String bindingStatus;

    private String requestId;

    private String failureReason;

    private Date updatedAt;

    private static final long serialVersionUID = 1L;
}
