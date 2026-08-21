package com.schoolwork.epsys.device.knowledge;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;

import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(properties = {
        "spring.cloud.nacos.discovery.enabled=false",
        "spring.cloud.discovery.enabled=false",
        "knowledge.work-order-ingestion.enabled=false"
})
@ActiveProfiles("test")
class WorkOrderCompletionServiceIntegrationTest {

    private static final int ORDER_ID = 99301;
    private static final String PROCESS = "检查供电后更换损坏保险丝";
    private static final String SOLUTION = "设备恢复运行并连续观察三十分钟";
    private static final String ROOT_CAUSE = "保险丝老化后熔断";
    private static final String VERIFICATION = "连续通电三十分钟无异常";
    private static final String PARTS = "保险丝";
    private static final String TAGS = "断电,保险丝";

    @Autowired
    private WorkOrderCompletionService service;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        cleanRows();
        insertInProgressOrder();
    }

    @AfterEach
    void tearDown() {
        cleanRows();
    }

    @Test
    void completionAndKnowledgeEventCommitTogether() throws Exception {
        WorkOrderCompletionService.CompletionResult result = service.complete(
                ORDER_ID, PROCESS, SOLUTION, ROOT_CAUSE, VERIFICATION, PARTS, TAGS);

        assertTrue(result.completed());
        assertNotNull(result.eventId());
        assertEquals("已完成", value("SELECT status FROM maintain_record WHERE id = ?", String.class));
        assertEquals(PROCESS, value("SELECT repair_process FROM maintain_record WHERE id = ?", String.class));
        assertEquals(SOLUTION, value("SELECT solution FROM maintain_record WHERE id = ?", String.class));
        assertEquals(VERIFICATION,
                value("SELECT verification_result FROM maintain_record WHERE id = ?", String.class));
        assertNotNull(value("SELECT end_time FROM maintain_record WHERE id = ?", Object.class));
        assertEquals(1, value("SELECT COUNT(*) FROM work_order_knowledge_outbox WHERE order_id = ?", Integer.class));

        String payload = value(
                "SELECT payload FROM work_order_knowledge_outbox WHERE order_id = ?", String.class);
        JsonNode event = objectMapper.readTree(payload);
        assertEquals("work-order-completed/v2", event.path("schema_version").asText());
        assertEquals("default", event.path("tenant_id").asText());
        assertEquals(Integer.toString(ORDER_ID), event.path("work_order_id").asText());
        assertEquals("99001", event.path("device_id").asText());
        assertEquals(PROCESS, event.path("repair_process").asText());
        assertEquals(SOLUTION, event.path("solution").asText());
        assertEquals(ROOT_CAUSE, event.path("root_cause").asText());
        assertEquals(VERIFICATION, event.path("verification_result").asText());
        assertEquals("电气设备", event.path("device_category").asText());
        assertEquals("断路保护器", event.path("device_model").asText());
    }

    @Test
    void repeatedCompletionDoesNotCreateAnotherEvent() {
        assertTrue(service.complete(
                ORDER_ID, PROCESS, SOLUTION, ROOT_CAUSE, VERIFICATION, PARTS, TAGS).completed());

        WorkOrderCompletionService.CompletionResult repeated = service.complete(
                ORDER_ID, PROCESS, SOLUTION, ROOT_CAUSE, VERIFICATION, PARTS, TAGS);

        assertFalse(repeated.completed());
        assertEquals(1, value("SELECT COUNT(*) FROM work_order_knowledge_outbox WHERE order_id = ?", Integer.class));
    }

    @Test
    void outboxFailureRollsBackWorkOrderCompletion() throws Exception {
        String eventId = "knowledge-event-" + sha256(
                "default:" + ORDER_ID + ":1:" + PROCESS + ":" + SOLUTION + ":"
                        + ROOT_CAUSE + ":" + VERIFICATION
        ).substring(0, 24);
        jdbcTemplate.update("""
                INSERT INTO work_order_knowledge_outbox
                  (event_id, tenant_id, order_id, order_version, trace_id, payload,
                   publish_status, retry_count, next_retry_at, created_at, updated_at)
                VALUES (?, 'default', ?, 1, 'duplicate-test', '{}',
                        'PENDING', 0, NOW(), NOW(), NOW())
                """, eventId, ORDER_ID);

        assertThrows(Exception.class, () -> service.complete(
                ORDER_ID, PROCESS, SOLUTION, ROOT_CAUSE, VERIFICATION, PARTS, TAGS));

        assertEquals("维护中", value("SELECT status FROM maintain_record WHERE id = ?", String.class));
        assertNull(value("SELECT repair_process FROM maintain_record WHERE id = ?", String.class));
        assertEquals(0, value("SELECT version FROM maintain_record WHERE id = ?", Integer.class));
    }

    private void insertInProgressOrder() {
        jdbcTemplate.update("""
                INSERT INTO devicecategory (id, category_name, description)
                VALUES (99001, '电气设备', '测试分类')
                ON DUPLICATE KEY UPDATE category_name = VALUES(category_name)
                """);
        jdbcTemplate.update("""
                INSERT INTO devicemodel (id, category_id, model_name, description)
                VALUES (99001, 99001, '断路保护器', '测试型号')
                ON DUPLICATE KEY UPDATE category_id = VALUES(category_id), model_name = VALUES(model_name)
                """);
        jdbcTemplate.update("""
                INSERT INTO deviceinstance (id, model_id, serial_number, status)
                VALUES (99001, 99001, 'KNOWLEDGE-TEST-99001', '维护中')
                ON DUPLICATE KEY UPDATE model_id = VALUES(model_id)
                """);
        jdbcTemplate.update("""
                INSERT INTO maintain_record
                  (id, device_id, tenant_id, maintenance_type, priority, description, status, version)
                VALUES (?, 99001, 'default', 'ELECTRICAL', 'NORMAL', '设备突然断电', '维护中', 0)
                """, ORDER_ID);
    }

    private <T> T value(String sql, Class<T> type) {
        return jdbcTemplate.queryForObject(sql, type, ORDER_ID);
    }

    private void cleanRows() {
        jdbcTemplate.update("DELETE FROM work_order_knowledge_outbox WHERE order_id = ?", ORDER_ID);
        jdbcTemplate.update("DELETE FROM maintain_record WHERE id = ?", ORDER_ID);
        jdbcTemplate.update("DELETE FROM deviceinstance WHERE id = 99001");
        jdbcTemplate.update("DELETE FROM devicemodel WHERE id = 99001");
        jdbcTemplate.update("DELETE FROM devicecategory WHERE id = 99001");
    }

    private static String sha256(String value) throws Exception {
        return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))
        );
    }
}
