package com.schoolwork.epsys.model.device;

import com.baomidou.mybatisplus.annotation.TableName;
import java.io.Serializable;
import java.util.Date;
import lombok.Data;

/**
 * @TableName devicemodel
 */
@TableName(value ="devicemodel")
@Data
public class Devicemodel implements Serializable {
    private Integer id;

    private Integer categoryId;

    private String modelName;

    private String description;

    private String image;

    private Date createAt;

    private static final long serialVersionUID = 1L;
}