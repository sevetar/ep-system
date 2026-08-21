package com.schoolwork.epsys.common.config;

import com.fasterxml.jackson.annotation.JsonAutoDetect;
import com.fasterxml.jackson.annotation.PropertyAccessor;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.jsontype.impl.LaissezFaireSubTypeValidator;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.interceptor.KeyGenerator;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.RedisSerializer;
import org.springframework.data.redis.serializer.StringRedisSerializer;
import org.springframework.data.redis.cache.RedisCacheConfiguration;
import org.springframework.data.redis.cache.RedisCacheManager;

import java.time.Duration;

@Configuration
@EnableCaching // 开启Spring Cache支持
public class RedisTemplateConfig {

    // 创建 RedisTemplate，并设置自定义序列化方式
    @Bean
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory redisConnectionFactory) {
        RedisTemplate<String, Object> redisTemplate = new RedisTemplate<>();
        redisTemplate.setConnectionFactory(redisConnectionFactory); // 使用 Spring Boot 自动配置的连接池

        // 设置自定义的Redis序列化方式
        redisTemplate.setValueSerializer(redisSerializer());
        redisTemplate.setKeySerializer(new StringRedisSerializer()); // 设置Key的序列化方式
        redisTemplate.setHashKeySerializer(new StringRedisSerializer()); // 设置Hash的Key的序列化方式
        redisTemplate.setHashValueSerializer(redisSerializer()); // 设置Hash的Value的序列化方式

        redisTemplate.afterPropertiesSet(); // 初始化配置
        return redisTemplate;
    }

    // 使用 GenericJackson2JsonRedisSerializer 进行序列化
    private RedisSerializer<Object> redisSerializer() {
        ObjectMapper objectMapper = new ObjectMapper();
        objectMapper.setVisibility(PropertyAccessor.ALL, JsonAutoDetect.Visibility.ANY);
        objectMapper.activateDefaultTyping(LaissezFaireSubTypeValidator.instance, ObjectMapper.DefaultTyping.NON_FINAL);
        return new GenericJackson2JsonRedisSerializer(objectMapper);
    }

    // 配置 Spring Cache 的 CacheManager，用于支持缓存操作
    @Bean
    public CacheManager cacheManager(RedisConnectionFactory redisConnectionFactory) {
        RedisCacheConfiguration cacheConfiguration = RedisCacheConfiguration.defaultCacheConfig()
                .entryTtl(Duration.ofDays(1)) // 设置缓存的默认过期时间为 1 天
                .disableCachingNullValues() // 禁止缓存空值
                .serializeKeysWith(RedisCacheConfiguration.defaultCacheConfig().getKeySerializationPair()) // 默认Key序列化方式
                .serializeValuesWith(RedisCacheConfiguration.defaultCacheConfig().getValueSerializationPair()); // 默认Value序列化方式

        return RedisCacheManager.builder(redisConnectionFactory)
                .cacheDefaults(cacheConfiguration) // 设置默认缓存配置
                .build();
    }

    // 自定义缓存Key的生成策略
    @Bean
    public KeyGenerator keyGenerator() {
        return (target, method, params) -> {
            // 使用类名、方法名和参数来生成缓存的Key
            StringBuilder sb = new StringBuilder();
            sb.append(target.getClass().getSimpleName()); // 目标类名
            sb.append(":");
            sb.append(method.getName()); // 方法名
            for (Object param : params) {
                sb.append(":").append(param); // 添加方法参数作为缓存Key的一部分
            }
            return sb.toString(); // 返回缓存Key
        };
    }
}
