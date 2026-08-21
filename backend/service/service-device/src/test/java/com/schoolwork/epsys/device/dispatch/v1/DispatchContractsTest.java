package com.schoolwork.epsys.device.dispatch.v1;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Validation;
import org.junit.jupiter.api.Test;

import static com.schoolwork.epsys.device.dispatch.v1.DispatchContracts.*;
import static org.junit.jupiter.api.Assertions.*;

class DispatchContractsTest {

    @Test
    void assignmentCommandRoundTripsAndValidates() throws Exception {
        AssignmentCommandV1 command = new AssignmentCommandV1(
                CONTRACT_VERSION, "trace-001", "event-001", "dispatch-001",
                "dispatch:dispatch-001:assign", DEFAULT_TENANT, "92001", "91001", 0);
        ObjectMapper mapper = new ObjectMapper();

        String json = mapper.writeValueAsString(command);
        AssignmentCommandV1 restored = mapper.readValue(json, AssignmentCommandV1.class);

        assertEquals(command, restored);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            assertTrue(factory.getValidator().validate(command).isEmpty());
        }
    }

    @Test
    void rejectsNonNumericIdsAndOversizedIdempotencyKey() {
        AssignmentCommandV1 command = new AssignmentCommandV1(
                CONTRACT_VERSION, "trace", "event", "dispatch", "x".repeat(301),
                DEFAULT_TENANT, "order-1", "worker-1", 0);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var violations = factory.getValidator().validate(command);
            assertEquals(3, violations.size());
        }
    }
}
