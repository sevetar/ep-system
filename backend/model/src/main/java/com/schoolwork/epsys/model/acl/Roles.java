package com.schoolwork.epsys.model.acl;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.util.Date;

/**
 * @TableName roles
 */
@TableName(value ="roles")
@Data
public class Roles implements Serializable {
    private Integer id;

    private String roleName;

    private String roleDesc;

    private Integer status;

    private Date createTime;

    private static final long serialVersionUID = 1L;
}