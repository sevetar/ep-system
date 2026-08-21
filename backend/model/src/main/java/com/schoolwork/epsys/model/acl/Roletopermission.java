package com.schoolwork.epsys.model.acl;

import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;

/**
 * @TableName roletopermission
 */
@TableName(value ="roletopermission")
@Data
public class Roletopermission implements Serializable {
    private Integer id;

    private Integer roleId;

    private Integer permissionId;

    private static final long serialVersionUID = 1L;
}