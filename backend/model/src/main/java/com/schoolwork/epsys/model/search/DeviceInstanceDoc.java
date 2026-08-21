package com.schoolwork.epsys.model.search;

import lombok.*;
import org.springframework.data.annotation.Id;
import org.springframework.data.elasticsearch.annotations.Document;

import java.util.Date;

import lombok.Data;
import lombok.Builder;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;
import org.springframework.data.elasticsearch.annotations.Field;
import org.springframework.data.elasticsearch.annotations.FieldType;

@Data // Lombok 注解，自动生成 getter/setter、toString 等方法
@Builder // Lombok 注解，提供 Builder 模式
@NoArgsConstructor // Lombok 注解，生成无参构造函数
@AllArgsConstructor // Lombok 注解，生成全参构造函数
@Document(indexName = "device_instance") // Elasticsearch 注解，指定索引名称为 "device_instance"
public class DeviceInstanceDoc {

    @Id // 标识该字段为 Elasticsearch 文档的唯一标识符
    private Integer id;

    @Field(type = FieldType.Integer) // 指定字段类型为 Integer，用于 Elasticsearch 映射
    private Integer modelId;

    @Field(type = FieldType.Text) // keyword 类型用于精确匹配，适合不需要分词的字段
    private String serialNumber;

    @Field(type = FieldType.Text) // keyword 类型，用于存储设备状态，支持精确匹配
    private String status; // 原来是 Object，ES 不支持泛型字段，转为 String

    @Field(type = FieldType.Date) // 指定字段类型为 Date，用于存储日期时间
    private Date createAt;

    @Field(type = FieldType.Text) // text 类型支持分词，适合模糊匹配的字段
    private String location; // 用于存储设备位置描述


}
