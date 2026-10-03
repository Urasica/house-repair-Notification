// Generated from schemas/openapi.json. Run npm run types to update.
export interface paths {
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Logout */
        post: operations["logout"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["getAuth"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/register": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Register */
        post: operations["register"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/catalog": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Catalog */
        get: operations["getCatalog"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Live */
        get: operations["getLive"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Ready */
        get: operations["getReadiness"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AccessMode
         * @enum {string}
         */
        AccessMode: "GUEST" | "MEMBER";
        /** AuthState */
        AuthState: {
            /** Csrftoken */
            csrfToken: string | null;
            user: components["schemas"]["User"] | null;
        };
        /** Catalog */
        Catalog: {
            /** Facilities */
            facilities: components["schemas"]["FacilityItem"][];
            /** Housingtypes */
            housingTypes: components["schemas"]["HousingItem"][];
            /**
             * Publishedat
             * Format: date-time
             */
            publishedAt: string;
            /** Rooms */
            rooms: components["schemas"]["CatalogItem"][];
            /** Symptoms */
            symptoms: components["schemas"]["SymptomItem"][];
            /** Version */
            version: string;
        };
        /** CatalogItem */
        CatalogItem: {
            /** Aliases */
            aliases?: string[];
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** ChatMessage */
        ChatMessage: {
            /** Citations */
            citations: components["schemas"]["Citation"][];
            /** Content */
            content: string;
            /**
             * Createdat
             * Format: date-time
             */
            createdAt: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Iscurrent */
            isCurrent: boolean;
            /**
             * Requestid
             * Format: uuid
             */
            requestId: string;
            /**
             * Role
             * @enum {string}
             */
            role: "USER" | "ASSISTANT";
        };
        /** ChatRequest */
        ChatRequest: {
            /** Content */
            content: string;
            /** Expectedrevision */
            expectedRevision: number;
            /**
             * Requestid
             * Format: uuid
             */
            requestId: string;
        };
        /** ChatResponse */
        ChatResponse: {
            /**
             * Answermode
             * @enum {string}
             */
            answerMode: "GROUNDED" | "CLARIFY" | "TEMPLATE";
            assistantMessage: components["schemas"]["ChatMessage"];
            /** Contextrevision */
            contextRevision: number;
            /** Disclaimer */
            disclaimer: string;
            /** Followupquestions */
            followUpQuestions: string[];
            /** Iscurrent */
            isCurrent: boolean;
            /**
             * Requestid
             * Format: uuid
             */
            requestId: string;
            status: components["schemas"]["GuidanceStatus"];
            userMessage: components["schemas"]["ChatMessage"];
        };
        /** Citation */
        Citation: {
            /**
             * Chunkid
             * Format: uuid
             */
            chunkId: string;
            /**
             * Documentversionid
             * Format: uuid
             */
            documentVersionId: string;
            /** Effectivedate */
            effectiveDate: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "LAW_CRITERIA" | "LH_OPERATION" | "SAFETY_SOURCE";
            /** Locator */
            locator: string;
            /**
             * Reviewuntil
             * Format: date-time
             */
            reviewUntil: string;
            /**
             * Reviewedat
             * Format: date-time
             */
            reviewedAt: string;
            /** Title */
            title: string;
            /** Url */
            url: string;
            /**
             * Use
             * @enum {string}
             */
            use: "RELATED" | "APPLICABLE";
        };
        /** Context */
        Context: {
            /** Answers */
            answers?: {
                [key: string]: string;
            };
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Facilityid
             * @default null
             */
            facilityId: string | null;
            /** @default null */
            housingType: components["schemas"]["HousingType"] | null;
            /**
             * Roomid
             * @default null
             */
            roomId: string | null;
            /**
             * Symptomid
             * @default null
             */
            symptomId: string | null;
        };
        /** ContextUpdate */
        ContextUpdate: {
            context: components["schemas"]["Context"];
            /** Expectedrevision */
            expectedRevision: number;
        };
        /** Credentials */
        Credentials: {
            /**
             * Email
             * Format: email
             */
            email: string;
            /**
             * Password
             * Format: password
             */
            password: string;
        };
        /**
         * ErrorCode
         * @enum {string}
         */
        ErrorCode: "AUTH_REQUIRED" | "AUTH_EXPIRED" | "UNAUTHORIZED" | "SESSION_EXPIRED" | "CATALOG_NOT_READY" | "CATALOG_UPDATED" | "CONTEXT_CONFLICT" | "SESSION_BUSY" | "REQUEST_IN_PROGRESS" | "REQUEST_FAILED" | "IDEMPOTENCY_CONFLICT" | "INVALID_SELECTION" | "INVALID_ANSWER" | "VALIDATION_ERROR" | "NOT_FOUND" | "RATE_LIMITED" | "SERVICE_UNAVAILABLE";
        /** ErrorDetail */
        ErrorDetail: {
            code: components["schemas"]["ErrorCode"];
            /** Details */
            details?: {
                [key: string]: unknown;
            };
            /** Message */
            message: string;
            /**
             * Traceid
             * Format: uuid
             */
            traceId: string;
        };
        /** ErrorResponse */
        ErrorResponse: {
            error: components["schemas"]["ErrorDetail"];
        };
        /** EvaluationRequest */
        EvaluationRequest: {
            /** Expectedrevision */
            expectedRevision: number;
            /**
             * Requestid
             * Format: uuid
             */
            requestId: string;
        };
        /** FacilityItem */
        FacilityItem: {
            /** Aliases */
            aliases?: string[];
            /** Id */
            id: string;
            /** Label */
            label: string;
            /** Roomids */
            roomIds: string[];
        };
        /** GuidanceResult */
        GuidanceResult: {
            /** Catalogversion */
            catalogVersion: string;
            /** Checks */
            checks: string[];
            /** Citations */
            citations: components["schemas"]["Citation"][];
            /** Contactdraft */
            contactDraft: string;
            /** Contextrevision */
            contextRevision: number;
            /** Disclaimer */
            disclaimer: string;
            /** Engineversion */
            engineVersion: string;
            /** Followupquestions */
            followUpQuestions: string[];
            /**
             * Generatedat
             * Format: date-time
             */
            generatedAt: string;
            /** Guidance */
            guidance: string[];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Iscurrent */
            isCurrent: boolean;
            /** Knowledgereleaseid */
            knowledgeReleaseId: string | null;
            /** Reasoncodes */
            reasonCodes: ("HAZARD_SIGNAL" | "HOUSING_OUT_OF_SCOPE" | "MISSING_INPUT" | "NO_APPLICABLE_SOURCE" | "SOURCE_CONFLICT" | "SOURCE_UNAVAILABLE" | "MATCHED_OPERATION_RULE")[];
            /**
             * Retaineduntil
             * Format: date-time
             */
            retainedUntil: string;
            /** Savedtohistory */
            savedToHistory: boolean;
            /** Sessionid */
            sessionId: string | null;
            status: components["schemas"]["GuidanceStatus"];
            summary: components["schemas"]["ResultSummary"];
        };
        /**
         * GuidanceStatus
         * @enum {string}
         */
        GuidanceStatus: "SAFETY_PRIORITY" | "OUT_OF_SCOPE" | "NEED_MORE_INFO" | "NEED_CONFIRMATION" | "GUIDANCE_AVAILABLE";
        /** HousingItem */
        HousingItem: {
            id: components["schemas"]["HousingType"];
            /** Label */
            label: string;
            /** Supported */
            supported: boolean;
        };
        /**
         * HousingType
         * @enum {string}
         */
        HousingType: "LH_CONSTRUCTION_RENTAL" | "LH_RENTAL_BEFORE_SALE" | "SOLD_OR_PRIVATE" | "OTHER" | "UNKNOWN";
        /** Option */
        Option: {
            /** Label */
            label: string;
            /** Value */
            value: string;
        };
        /** Question */
        Question: {
            /** Interruptvalues */
            interruptValues?: string[];
            /** Label */
            label: string;
            /** Options */
            options: components["schemas"]["Option"][];
            /** Questionid */
            questionId: string;
            /** Required */
            required: boolean;
            /**
             * Type
             * @default singleChoice
             * @constant
             */
            type: "singleChoice";
        };
        /** Readiness */
        Readiness: {
            /** Catalogready */
            catalogReady: boolean;
            /** Ragready */
            ragReady: boolean;
            /**
             * Status
             * @constant
             */
            status: "ok";
        };
        /**
         * RequestKind
         * @enum {string}
         */
        RequestKind: "SURVEY" | "CHAT";
        /** RequestState */
        RequestState: {
            kind: components["schemas"]["RequestKind"];
            /**
             * Requestid
             * Format: uuid
             */
            requestId: string;
            /** Response */
            response: components["schemas"]["GuidanceResult"] | components["schemas"]["ChatResponse"] | null;
            /** Retryafterms */
            retryAfterMs: number | null;
            state: components["schemas"]["RequestStatus"];
        };
        /**
         * RequestStatus
         * @enum {string}
         */
        RequestStatus: "PROCESSING" | "COMPLETED" | "FAILED";
        /** ResultSummary */
        ResultSummary: {
            /** Answerlabels */
            answerLabels: string[];
            /** Description */
            description: string;
            /** Facilitylabel */
            facilityLabel: string;
            /** Housinglabel */
            housingLabel: string;
            /** Roomlabel */
            roomLabel: string;
            /** Symptomlabel */
            symptomLabel: string;
        };
        /** Session */
        Session: {
            accessMode: components["schemas"]["AccessMode"];
            /** Catalogversion */
            catalogVersion: string;
            context: components["schemas"]["Context"];
            /**
             * Createdat
             * Format: date-time
             */
            createdAt: string;
            /** Currentresultid */
            currentResultId: string | null;
            /**
             * Expiresat
             * Format: date-time
             */
            expiresAt: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Knowledgereleaseid */
            knowledgeReleaseId: string | null;
            /** Revision */
            revision: number;
        };
        /** SymptomItem */
        SymptomItem: {
            /** Aliases */
            aliases?: string[];
            /** Facilityids */
            facilityIds: string[];
            /** Id */
            id: string;
            /** Label */
            label: string;
        };
        /** User */
        User: {
            /**
             * Createdat
             * Format: date-time
             */
            createdAt: string;
            /** Email */
            email: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Credentials"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthState"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    logout: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getAuth: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthState"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    register: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Credentials"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["User"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getCatalog: {
        parameters: {
            query?: {
                version?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Catalog"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getLive: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getReadiness: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Readiness"];
                };
            };
            /** @description Unprocessable Entity */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
