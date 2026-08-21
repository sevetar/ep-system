package com.schoolwork.epsys.model.acl;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * @TableName permissions
 */
@TableName(value ="permissions")
@Data
public class Permissions implements Serializable {
    private Integer id;

    private String permissionName;

    private String permissionCode;

    private String permissionDesc;

    private Date createdAt;

    private static final long serialVersionUID = 1L;
}