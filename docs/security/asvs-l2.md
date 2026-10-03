# Alerta Next – samoocena OWASP ASVS 5.0, poziom 2

Stan na 2026-09-26, wersja 0.18.0 (po wzmocnieniach G1–G4, G7, G11, G12). Standard: **OWASP ASVS 5.0.0** (maj 2025), wymagania poziomów L1 i L2 – **253**.
Ocena wykonana na kodzie (backend, frontend, konfiguracja nginx, manifesty i chart Helm), nie na konkretnej
instalacji: wymagania zależne od wdrożenia (TLS na ingress/F5, HSTS, serwer autoryzacji SSO, SIEM) oznaczono „po
stronie wdrożenia”.

| Status | Liczba | Znaczenie |
|---|---|---|
| ✅ spełnione | 162 | wymaganie spełnione w aplikacji (dowód w kolumnie „Uzasadnienie”) |
| 🟡 częściowo | 10 | spełnione z zastrzeżeniem – działanie w części C |
| ❌ niespełnione | 0 | – |
| 🏢 wdrożenie | 24 | zależy od infrastruktury / konfiguracji organizacji (ingress, F5, SSO, SIEM, Vault) |
| ➖ nie dotyczy | 57 | funkcji nie ma w aplikacji (np. wgrywanie plików, WebSocket, GraphQL, WebRTC, SAML) |

**Wniosek:** aplikacja spełnia rdzeń L2 (uwierzytelnianie, sesje, autoryzacja, CSRF/CSP, audyt, obsługa błędów,
kryptografia). Luki z pierwszej oceny usunięto w 0.18.0 (część C), widok własnych sesji (G8) w 0.37.0; zostały: limit częstotliwości
na ingress (G5), MFA dla kont lokalnych (G6 – na produkcji SSO z MFA), TLS wewnątrz klastra (G9) i procesy organizacji
(G10, cykliczny skan SBOM).

Dokument jest też **dokumentacją bezpieczeństwa**, której ASVS wymaga wprost (część A) – przy zmianie zachowania
aplikacji aktualizujemy go razem z kodem.

---

## Część A – dokumentacja bezpieczeństwa

### A.1 Walidacja danych wejściowych (V2.1.1, V2.1.2)
- Wszystkie żądania API walidowane na serwerze (Bean Validation na rekordach żądań + reguły w serwisach); UI
  waliduje tylko dla wygody.
- **Formaty:** kody środowisk `^[A-Z][A-Z0-9_-]{0,31}$`; nazwy Alertmanagerów `^[a-z][a-z0-9-]{0,31}$`; nazwy
  heartbeatów `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` (prefiks `watchdog:` zarezerwowany); loginy wg `User.normalizeUsername`;
  teksty z limitami długości (notatka 4000, komentarz wyciszenia 1000, wyszukiwanie 200, nazwy 128); daty ISO-8601;
  ważności, statusy i akcje jako listy dozwolonych wartości (enum).
- **Spójność danych łącznych:** okno czasu `from < to` (oś czasu ≤ 31 dni); okno serwisowe: koniec po starcie, ≤ 30 dni,
  start ≤ 90 dni naprzód, etykiety dodatkowe nie mogą nadpisywać warunków środowiska; klucz API może wysyłać tylko dla
  swoich środowisk; wyciszenie z konsoli zawsze obejmuje etykiety środowiska alertu (+ co najmniej jedną więcej).
- **Linki z danych** (runbook, generatorURL) – tylko `http(s)`, maks. 2048 znaków; inne schematy odrzucane.

### A.2 Limity biznesowe i funkcje kosztowne (V2.1.3, V2.3.2, V15.1.3, V15.2.2)
| Obszar | Limit |
|---|---|
| Ingest | ≤ 1000 alertów w żądaniu (`alerta.alerts.max-alerts-per-request`), ciało ≤ 5 MB (nginx) |
| Pozostałe API | ciało ≤ 1 MB |
| Lista alertów | strony po 500 |
| Eksport CSV | ≤ 10 000 wierszy (kosztowny – ogranicza liczba wierszy) |
| Akcje grupowe | ≤ 1000 alertów |
| Oś czasu | ≤ 500 alertów, okno ≤ 31 dni; historia alertu ≤ 400 dni |
| Wyciszenia | 5 min – 30 dni; okna serwisowe ≤ 30 dni, ≤ 90 dni naprzód |
| Klucze API | ważność ≤ 2 lata |
| Konta tymczasowe | ≤ 180 dni |

Funkcje kosztowne: eksport CSV, oś czasu, raporty (MTTA/MTTR) – ograniczone limitami powyżej i indeksami; odporność
na przeciążenie potwierdzona testem obciążeniowym (`load/README.md`: ok. 10× intensywnej awarii na 2 replikach).

### A.3 Uwierzytelnianie i ochrona przed zgadywaniem haseł (V6.1.1, V6.1.3)
- **Ścieżki:** (1) konta lokalne – login + hasło; (2) SSO OpenID Connect (kod autoryzacji + PKCE, state, nonce).
  Tryb kont lokalnych w konfiguracji (nigdy w UI): `ENABLED` / `BREAK_GLASS_ONLY` (tylko wymienione konta awaryjne) /
  `DISABLED`. **Zalecenie produkcyjne:** SSO z MFA u dostawcy + `BREAK_GLASS_ONLY`.
- **Hasła lokalne:** min. 12 znaków (16 dla kont z rolą administracyjną), maks. 128; bez reguł złożoności; odrzucane
  popularne hasła (~30 tys. z listy SecLists top 1M), zawierające login i **słowa kontekstowe** z
  `alerta.passwords.forbidden-words` (domyślnie „alerta”; organizacja dopisuje nazwę firmy, systemów, projektów); Argon2id;
  bez okresowej zmiany.
- **Przeciw zgadywaniu:** po 5 nieudanych próbach konto blokowane na 15 min, każda kolejna blokada podwaja czas (do
  1 h); z jednego adresu IP maks. 20 nieudanych prób na 15 min; odpowiedź nie zdradza, czy konto istnieje; wszystko
  w audycie i metrykach (`alerta_auth_*`).
- **Konto pierwszego administratora i reset:** tylko przez CLI `alerta-admin` (dostęp `kubectl exec`) lub administratora
  dostępu – hasło jednorazowe z CSPRNG, obowiązkowa zmiana przy pierwszym logowaniu, ważne 72 h
  (`alerta.passwords.one-time-validity`) – potem odrzucane, administrator wydaje nowe.
- **Adres klienta** (limity na IP, audyt): nginx wierzy `X-Forwarded-For` tylko od pośredników z `TRUSTED_PROXIES`
  (ingress, load balancer); bez listy liczy się bezpośrednie połączenie. Klient nie może podać własnego adresu.

### A.4 Sesje (V7.1.1–V7.1.3, V7.6.1)
- Sesja serwerowa w bazie (Spring Session JDBC), cookie `__Host-SESSION` (`HttpOnly; Secure; SameSite=Strict; Path=/`,
  bez Domain), identyfikator 256 bitów, nowy przy każdym logowaniu. Wylogowanie: sesja unieważniona, `Clear-Site-Data`,
  pełne przeładowanie strony.
- **Bezczynność:** 30 min dla kont z uprawnieniami administracyjnymi, 8 h dla pozostałych (dyżur); **limit absolutny**
  12 h; konta kiosku (tylko odczyt, ekrany ścienne) – bez limitu bezczynności, absolutnie 30 dni. Ostrzeżenie w UI 5 min
  przed wygaśnięciem.
- **Sesje równoległe:** bez limitu – dyżurny pracuje na kilku ekranach, kiosk na wielu telewizorach; ryzyko ograniczają
  limity czasu i zakończenie wszystkich sesji przy zmianie hasła, blokadzie, wyłączeniu i resecie.
- **SSO:** sesja aplikacji ma własne limity niezależnie od sesji u dostawcy; wylogowanie kończy też sesję SSO
  (`end-session`); utworzenie sesji wymaga kliknięcia „Zaloguj przez SSO”.

### A.5 Autoryzacja (V8.1.1, V8.1.2)
- Domyślnie wszystko zamknięte (`denyAll`); każdy punkt końcowy ma `@PreAuthorize` z uprawnieniem.
- **Role per środowisko:** Obserwator (podgląd), Operator (akcje na alertach), Opiekun (okna serwisowe, heartbeaty);
  **globalne:** Administrator dostępu, Audytor (rozdział obowiązków – administrator nie czyta audytu, dopóki nie dostanie
  roli Audytora, co samo trafia do audytu). Szczegóły: [instrukcja wdrożenia](../deployment/README.pl.md), rozdział 2 (role i uprawnienia).
- Dane filtrowane po środowiskach w zapytaniach; obiekt spoza uprawnień → 404 (nie zdradza istnienia). Kwarantanna –
  tylko administrator dostępu. Uprawnienia liczone przy każdym żądaniu z bazy (zmiana działa natychmiast).
- Poziom pól: brak ograniczeń poza tym, że sekrety (skróty haseł, klucze API, sekrety integracji) nigdy nie są zwracane.

### A.6 Kryptografia – inwentarz (V11.1.2)
| Zastosowanie | Algorytm / mechanizm | Gdzie |
|---|---|---|
| Hasła lokalne | Argon2id (19 MiB, 2 iteracje, 1 wątek, sól 16 B, skrót 32 B) | `PasswordConfig` |
| Klucze API | `ank_<prefiks>_<sekret>`, ~238 bitów z `SecureRandom`; w bazie SHA-256 | `ApiKeyService` |
| Hasła jednorazowe | `SecureRandom`, alfabet bez znaków mylących | `OneTimePasswords` |
| Identyfikator sesji | 32 bajty z `SecureRandom` (256 bitów, base64url) | `SessionCookies` |
| Token CSRF | UUID (`SecureRandom`), Spring Security | cookie `__Host-XSRF-TOKEN` |
| ID token SSO | podpis RS256/ES256 dostawcy, klucze z `jwks_uri` | Spring Security / Nimbus |
| TLS | ingress/F5 (przychodzące), JDK 25 (wychodzące do Alertmanagera, SSO, bazy) | platforma / `HttpClients` |
| Sekrety | Kubernetes Secret / HashiCorp Vault (CSI) – nie w obrazach, nie w ConfigMapie | Helm `secrets.mode` |

Klucze kryptograficzne w aplikacji: brak własnych kluczy do szyfrowania/podpisu. Certyfikaty TLS i klucze SSO należą
do platformy i dostawcy tożsamości.

### A.7 Komunikacja (V13.1.1)
| Z → do | Protokół | Uwierzytelnienie |
|---|---|---|
| Przeglądarka → ingress/F5 | HTTPS | sesja (cookie) + CSRF |
| Alertmanager / nadawcy → ingress | HTTPS | klucz API (Bearer) |
| Ingress → frontend (nginx) → backend | HTTP w klastrze (mTLS, jeśli siatka Istio) | – (izolacja siecią) |
| Backend → PostgreSQL | TCP, TLS opcjonalnie (`sslmode=verify-full`) | login + hasło (osobne konto migracji) |
| Backend → Alertmanager(y) API | HTTP(S), własne CA | token / basic (opcjonalnie) |
| Backend → dostawca OIDC | HTTPS | sekret klienta |
| Prometheus → backend :8081 | HTTP (metryki, health) | – (port niepublikowany przez ingress) |
| ELK/SIEM ← logi | stdout / plik JSON (agent organizacji) | po stronie agenta |

Aplikacja nie łączy się z niczym poza powyższym (brak telemetrii, CDN, zewnętrznych czcionek).

### A.8 Klasyfikacja danych (V14.1.1, V14.1.2, V14.2.4)
| Klasa | Dane | Ochrona |
|---|---|---|
| **Tajne** | skróty haseł, skróty kluczy API, sekrety integracji (baza, Alertmanager, OIDC) | nigdy w odpowiedziach ani logach; sekrety tylko z Secret/Vault; skróty jednokierunkowe |
| **Poufne** | alerty (nazwy systemów, adresy, opisy awarii), notatki, dziennik audytu, dane kont (login, nazwa, e-mail) | tylko po zalogowaniu i wg uprawnień; TLS; audyt dostępu administracyjnego; retencja alertów wg klasy środowiska (PROD 400 dni …), audyt tylko dopisywany |
| **Wewnętrzne** | konfiguracja w użyciu, metryki, wersja | stan systemu – tylko administrator/audytor; metryki na porcie niepublikowanym |

W przeglądarce: tylko cookie sesji (HttpOnly) i preferencje w localStorage; `Cache-Control: no-store` na API i stronie.

### A.9 Inwentarz logów (V16.1.1)
| Log | Treść | Format / miejsce | Retencja |
|---|---|---|---|
| Żądania HTTP | metoda, ścieżka (bez query), status, czas, użytkownik, IP, identyfikator żądania | stdout (tekst lub ECS) + plik `/var/log/alerta/alerta-next.json` (ECS) | wg ELK |
| Audyt | każda zmiana dostępu, logowanie (udane/nieudane, SSO), odmowa dostępu, odrzucony token CSRF, akcje na alertach, eksporty, wyciszenia | tabela `audit_log` (tylko dopisywanie – wyzwalacz) + logger `io.alertanext.audit` → ELK/SIEM (pola i lista akcji: instrukcja wdrożenia 9.1) | baza: bez usuwania; ELK wg polityki organizacji |
| Historia alertu | zdarzenia alertu (wystąpienia, akcje, notatki) | tabela `alert_events` | razem z alertem (retencja środowiska) |
| Błędy | nieoczekiwane wyjątki ze stosem wywołań (tylko w logu, klient dostaje identyfikator) | stdout / plik | wg ELK |

Znaczniki czasu w UTC. Hasła, klucze API, tokeny i ciasteczka nie są logowane. Wartości z zewnątrz (login przy
logowaniu, nazwy alertów) w logu tekstowym bez znaków sterujących (`LogSafe`).

### A.10 Zależności (V15.1.1, V15.1.2)
- Minimum zależności (zasada projektu); npm z `save-exact` i `npm ci`; obrazy bazowe przypięte po wersji; wydania jako
  obrazy z digestem.
- **SBOM (CycloneDX)** w każdym obrazie: backend – `META-INF/sbom/application.cdx.json` w jarze (wtyczka CycloneDX,
  Spring Boot), frontend – `/usr/share/sbom/alerta-next-frontend.cdx.json` (`npm sbom`, nieserwowany przez nginx).
- **Terminy usuwania podatności** w zależnościach i obrazach bazowych (od publikacji poprawki): krytyczne – 7 dni,
  wysokie – 30 dni, średnie i niskie – przy najbliższym wydaniu (najpóźniej 90 dni). Przegląd zależności (Angular,
  Spring Boot, JDK, nginx, PostgreSQL) raz w miesiącu; wersje główne Angulara i Spring Boota – w ciągu 6 miesięcy
  od wydania. Wykrywanie: `deploy/scan-images.sh <wersja>` (Trivy w kontenerze, HIGH/CRITICAL, obrazy wydania + obraz
  bazy informacyjnie) – **workflow wydania (`.github/workflows/release.yml`) nie wypycha wydania z podatnością, dla której jest
  poprawka**, a `ci.yml` oznacza taki PR na czerwono; obrazy budowane z `--pull`, pakiety Alpine frontendu aktualizowane przy każdym
  wydaniu. Po stronie organizacji dodatkowo skan w rejestrze (np. Xray). Pierwszy skan (2026-09-28): Tomcat 11.0.24 – 3×
  CRITICAL (ograniczenia i uwierzytelnianie DIGEST/FORM samego Tomcata, u nas nieużywane) → 11.0.26 przed Spring
  Bootem; libexpat HIGH w obrazie nginx → `apk upgrade`; w 0.22.1 oba obrazy bez HIGH/CRITICAL.

---

## Część B – ocena wymagań

Kolumna „Wymaganie” to skrót treści ASVS (pełny tekst: OWASP ASVS 5.0.0).



### V1 Encoding and Sanitization

✅ 15 · ➖ 12

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V1.1.1 | 2 | Input is decoded or unescaped into a canonical form only once, it is only decoded when encoded data in that form is expected, and that this is… | ✅ | Dane wejściowe dekodowane raz przez framework (Spring MVC/Jackson), bez ręcznego dekodowania po walidacji. |
| V1.1.2 | 2 | The application performs output encoding and escaping either as a final step before being used by the interpreter for which it is intended or by… | ✅ | Kodowanie na końcu: Angular (interpolacja), parametry SQL (JdbcClient), Jackson dla JSON. |
| V1.2.1 | 1 | Output encoding for an HTTP response, HTML document, or XML document is relevant for the context required, such as encoding the relevant… | ✅ | Angular koduje kontekstowo; zakaz innerHTML/bypassSecurityTrust* (zasada projektu), Trusted Types w CSP. |
| V1.2.2 | 1 | When dynamically building URLs, untrusted data is encoded according to its context (e.g., URL encoding or base64url encoding for query or path… | ✅ | Adresy budowane przez Router/HttpClient (kodowanie parametrów); linki z danych (runbook, generatorURL) przepuszczane tylko dla http/https (`AlertIngestService.safeUrl`). |
| V1.2.3 | 1 | Output encoding or escaping is used when dynamically building JavaScript content (including JSON), to avoid changing the message or document… | ✅ | JSON wyłącznie przez Jackson; brak dynamicznego JavaScriptu. |
| V1.2.4 | 1 | Data selection or database queries (e.g., SQL, HQL, NoSQL, Cypher) use parameterized queries, ORMs, entity frameworks, or are otherwise protected… | ✅ | Wszystkie zapytania parametryzowane (JdbcClient `:param`, JPA); nazwy etykiet w JSONB też jako parametry (`labels ->> :labelName`). |
| V1.2.5 | 1 | The application protects against OS command injection and that operating system calls use parameterized OS queries or use contextual command line… | ➖ | Aplikacja nie wywołuje poleceń systemu operacyjnego. |
| V1.2.6 | 2 | The application protects against LDAP injection vulnerabilities, or that specific security controls to prevent LDAP injection have been implemented. | ➖ | Brak zapytań LDAP (AD przez SSO/OIDC; plan NOC z LDAP – zob. uwagi). |
| V1.2.7 | 2 | The application is protected against XPath injection attacks by using query parameterization or precompiled queries. | ➖ | Brak XPath. |
| V1.2.8 | 2 | LaTeX processors are configured securely (such as not using the "--shell-escape" flag) and an allowlist of commands is used to prevent LaTeX… | ➖ | Brak LaTeX. |
| V1.2.9 | 2 | The application escapes special characters in regular expressions (typically using a backslash) to prevent them from being misinterpreted as… | ✅ | Wartości w matcherach wyciszeń Alertmanagera escapowane jak Go `regexp.QuoteMeta` (`EnvironmentMatchers.quote`). |
| V1.3.1 | 1 | All untrusted HTML input from WYSIWYG editors or similar is sanitized using a well-known and secure HTML sanitization library or framework feature. | ➖ | Brak edytorów WYSIWYG; notatki to zwykły tekst. |
| V1.3.2 | 1 | The application avoids the use of eval() or other dynamic code execution features such as Spring Expression Language (SpEL). Where there is no… | ✅ | Brak eval/SpEL na danych użytkownika (SpEL tylko w stałych `@PreAuthorize`). |
| V1.3.3 | 2 | Data being passed to a potentially dangerous context is sanitized beforehand to enforce safety measures, such as only allowing characters which… | ✅ | Limity długości (Bean Validation `@Size`), treści tylko jako tekst. |
| V1.3.4 | 2 | User-supplied Scalable Vector Graphics (SVG) scriptable content is validated or sanitized to contain only tags and attributes (such as draw… | ➖ | Brak wgrywania SVG. |
| V1.3.5 | 2 | The application sanitizes or disables user-supplied scriptable or expression template language content, such as Markdown, CSS or XSL stylesheets,… | ➖ | Brak Markdown/CSS/XSL od użytkownika. |
| V1.3.6 | 2 | The application protects against Server-side Request Forgery (SSRF) attacks, by validating untrusted data against an allowlist of protocols,… | ✅ | Serwer nie pobiera adresów z danych użytkownika; połączenia wychodzące tylko do adresów z konfiguracji (Alertmanager, dostawca OIDC). |
| V1.3.7 | 2 | The application protects against template injection attacks by not allowing templates to be built based on untrusted input. Where there is no… | ➖ | Brak szablonów budowanych z danych (świadomie bez nunjucks ze starej Alerty). |
| V1.3.8 | 2 | The application appropriately sanitizes untrusted input before use in Java Naming and Directory Interface (JNDI) queries and that JNDI is… | ➖ | Brak JNDI z danych użytkownika. |
| V1.3.9 | 2 | The application sanitizes content before it is sent to memcache to prevent injection attacks. | ➖ | Brak memcache. |
| V1.3.10 | 2 | Format strings which might resolve in an unexpected or malicious way when used are sanitized before being processed. | ✅ | Formatowanie przez SLF4J `{}` i `String.formatted` z danymi jako argumentami, nie jako wzorcem. |
| V1.3.11 | 2 | The application sanitizes user input before passing to mail systems to protect against SMTP or IMAP injection. | ➖ | Aplikacja nie wysyła poczty (plan powiadomień – do oceny przy wdrożeniu). |
| V1.4.1 | 2 | The application uses memory-safe string, safer memory copy and pointer arithmetic to detect or prevent stack, buffer, or heap overflows. | ✅ | Języki z zarządzaną pamięcią (Java, TypeScript). |
| V1.4.2 | 2 | Sign, range, and input validation techniques are used to prevent integer overflows. | ✅ | Zakresy liczb walidowane (`@Min/@Max`, limity okresów, rozmiarów stron). |
| V1.4.3 | 2 | Dynamically allocated memory and resources are released, and that references or pointers to freed memory are removed or set to null to prevent… | ✅ | Zarządzana pamięć; zasoby w try-with-resources / zarządzane przez Springa. |
| V1.5.1 | 1 | The application configures XML parsers to use a restrictive configuration and that unsafe features such as resolving external entities are… | ➖ | Aplikacja nie parsuje XML. |
| V1.5.2 | 2 | Deserialization of untrusted data enforces safe input handling, such as using an allowlist of object types or restricting client-defined object… | ✅ | JSON przez Jackson bez polimorficznej deserializacji; Spring Session serializuje tylko własne obiekty w bazie (nie dane z zewnątrz). |

### V2 Validation and Business Logic

✅ 10 · 🟡 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V2.1.1 | 1 | The application's documentation defines input validation rules for how to check the validity of data items against an expected structure. This… | ✅ | Zasady walidacji: sekcja A.1 tego dokumentu + Bean Validation w kontrolerach. |
| V2.1.2 | 2 | The application's documentation defines how to validate the logical and contextual consistency of combined data items, such as checking that… | ✅ | Sekcja A.1 (spójność: zakresy dat, klasy środowisk, klucz ↔ środowiska). |
| V2.1.3 | 2 | Expectations for business logic limits and validations are documented, including both per-user and globally across the application. | ✅ | Limity biznesowe: sekcja A.2. |
| V2.2.1 | 1 | Input is validated to enforce business or functional expectations for that input. This should either use positive validation against an allow list… | ✅ | Walidacja pozytywna: wzorce nazw (środowiska, Alertmanagery, heartbeaty), listy dozwolonych wartości (enumy), zakresy. |
| V2.2.2 | 1 | The application is designed to enforce input validation at a trusted service layer. While client-side validation improves usability and should be… | ✅ | Walidacja na serwerze (Bean Validation, serwisy); UI tylko pomocniczo. |
| V2.2.3 | 2 | The application ensures that combinations of related data items are reasonable according to the pre-defined rules. | ✅ | Np. okno czasu (from < to, ≤ 31 dni), okna serwisowe (koniec po starcie, ≤ 30 dni, ≤ 90 dni wyprzedzenia). |
| V2.3.1 | 1 | The application will only process business logic flows for the same user in the expected sequential step order and without skipping steps. | ✅ | Wymuszona zmiana hasła blokuje wszystko inne (`SessionPolicyFilter`); przejścia stanów alertu sprawdzane (`Transition`). |
| V2.3.2 | 2 | Business logic limits are implemented per the application's documentation to avoid business logic flaws being exploited. | ✅ | Limity z sekcji A.2 egzekwowane w kodzie (np. 1000 alertów na żądanie, 500 w eksporcie/osi czasu, czasy wyciszeń). |
| V2.3.3 | 2 | Transactions are being used at the business logic level such that either a business logic operation succeeds in its entirety or it is rolled back… | ✅ | Operacje w transakcjach (`@Transactional`); okna serwisowe w wielu Alertmanagerach „wszystkie albo żaden”. |
| V2.3.4 | 2 | Business logic level locking mechanisms are used to ensure that limited quantity resources (such as theater seats or delivery slots) cannot be… | ✅ | Blokady wierszy (`FOR UPDATE`), `ON CONFLICT`, blokady zadań cyklicznych (`JobLock`), wersjonowanie encji. |
| V2.4.1 | 2 | Anti-automation controls are in place to protect against excessive calls to application functions that could lead to data exfiltration,… | 🟡 | Logowanie: limity na konto i IP; ingest: limit alertów na żądanie. Brak ogólnego limitu częstotliwości dla API (zob. luka G5). |

### V3 Web Frontend Security

✅ 15 · 🏢 2 · ➖ 2

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V3.2.1 | 1 | Security controls are in place to prevent browsers from rendering content or functionality in HTTP responses in an incorrect context (e.g., when… | ✅ | API: `Content-Type: application/json`, `nosniff`, CSP `default-src 'none'` na odpowiedziach API. |
| V3.2.2 | 1 | Content intended to be displayed as text, rather than rendered as HTML, is handled using safe rendering functions (such as createTextNode or… | ✅ | Angular renderuje tekst przez interpolację (textContent); zakaz innerHTML. |
| V3.3.1 | 1 | Cookies have the 'Secure' attribute set, and if the '\__Host-' prefix is not used for the cookie name, the '__Secure-' prefix must be used for the… | ✅ | Przez HTTPS ciasteczka `__Host-SESSION` i `__Host-XSRF-TOKEN` z `Secure` (`SessionCookies`, test `cookiesAreHostPrefixedAndSessionIdsHave256Bits`); bez prefiksu tylko przy teście po zwykłym HTTP. |
| V3.3.2 | 2 | Each cookie's 'SameSite' attribute value is set according to the purpose of the cookie, to limit exposure to user interface redress attacks and… | ✅ | `SameSite=Strict` dla sesji i tokenu CSRF. |
| V3.3.3 | 2 | Cookies have the '__Host-' prefix for the cookie name unless they are explicitly designed to be shared with other hosts. | ✅ | Prefiks `__Host-` (Path=/, bez Domain) dla sesji i tokenu CSRF. |
| V3.3.4 | 2 | If the value of a cookie is not meant to be accessible to client-side scripts (such as a session token), the cookie must have the 'HttpOnly'… | ✅ | Sesja `HttpOnly`; token sesji nigdy w odpowiedzi ani w JS. |
| V3.4.1 | 1 | A Strict-Transport-Security header field is included on all responses to enforce an HTTP Strict Transport Security (HSTS) policy. A maximum age of… | 🏢 | HSTS ustawia warstwa kończąca TLS (ingress / F5) – do skonfigurowania przy wdrożeniu (max-age ≥ 1 rok, includeSubDomains). |
| V3.4.2 | 1 | The Cross-Origin Resource Sharing (CORS) Access-Control-Allow-Origin header field is a fixed value by the application, or if the Origin HTTP… | ✅ | Brak CORS – UI i API pod jednym originem; nagłówki CORS nie są wysyłane. |
| V3.4.3 | 2 | HTTP responses include a Content-Security-Policy response header field which defines directives to ensure the browser only loads and executes… | ✅ | CSP z nonce per żądanie, bez `unsafe-inline`, `object-src 'none'`, Trusted Types; API: `default-src 'none'`. |
| V3.4.4 | 2 | All HTTP responses contain an 'X-Content-Type-Options: nosniff' header field. This instructs browsers not to use content sniffing and MIME type… | ✅ | `X-Content-Type-Options: nosniff` (nginx dla UI, Spring Security dla API). |
| V3.4.5 | 2 | The application sets a referrer policy to prevent leakage of technically sensitive data to third-party services via the 'Referer' HTTP request… | ✅ | `Referrer-Policy: no-referrer`. |
| V3.4.6 | 2 | The web application uses the frame-ancestors directive of the Content-Security-Policy header field for every HTTP response to ensure that it… | ✅ | `frame-ancestors 'none'` + `X-Frame-Options: DENY`. |
| V3.5.1 | 1 | Verify that, if the application does not rely on the CORS preflight mechanism to prevent disallowed cross-origin requests to use sensitive… | ✅ | Ochrona CSRF (Spring Security, tryb SPA, token w nagłówku) + `SameSite=Strict`; ingest bez sesji (tylko klucz API w nagłówku). |
| V3.5.2 | 1 | Verify that, if the application relies on the CORS preflight mechanism to prevent disallowed cross-origin use of sensitive functionality, it is… | ➖ | Nie polegamy na preflight CORS (CSRF token). |
| V3.5.3 | 1 | HTTP requests to sensitive functionality use appropriate HTTP methods such as POST, PUT, PATCH, or DELETE, and not methods defined by the HTTP… | ✅ | Zmiany stanu tylko POST/PUT/PATCH/DELETE; GET bez skutków ubocznych. |
| V3.5.4 | 2 | Separate applications are hosted on different hostnames to leverage the restrictions provided by same-origin policy, including how documents or… | 🏢 | Alerta Next na własnej nazwie hosta (zalecenie w dokumentacji wdrożenia). |
| V3.5.5 | 2 | Messages received by the postMessage interface are discarded if the origin of the message is not trusted, or if the syntax of the message is invalid. | ➖ | Brak `postMessage`. |
| V3.7.1 | 2 | The application only uses client-side technologies which are still supported and considered secure. Examples of technologies which do not meet… | ✅ | Nowoczesny, wspierany Angular 22; brak wtyczek przeglądarki. |
| V3.7.2 | 2 | The application will only automatically redirect the user to a different hostname or domain (which is not controlled by the application) where the… | ✅ | Jedyne przekierowanie poza aplikację: do skonfigurowanego dostawcy OIDC (logowanie/wylogowanie). |

### V4 API and Web Service

✅ 1 · 🟡 1 · 🏢 2 · ➖ 6

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V4.1.1 | 1 | Every HTTP response with a message body contains a Content-Type header field that matches the actual content of the response, including the… | ✅ | Odpowiedzi z `Content-Type` i `charset=utf-8` (JSON, CSV, HTML). |
| V4.1.2 | 2 | Only user-facing endpoints (intended for manual web-browser access) automatically redirect from HTTP to HTTPS, while other services or endpoints… | 🏢 | Przekierowanie HTTP→HTTPS tylko dla UI – po stronie ingress/F5. |
| V4.1.3 | 2 | Any HTTP header field used by the application and set by an intermediary layer, such as a load balancer, a web proxy, or a backend-for-frontend… | 🟡 | nginx ustawia `X-Forwarded-For` na adres ustalony z zaufanych pośredników (`TRUSTED_PROXIES`), `X-Request-ID`, `X-Forwarded-Port`; `X-Forwarded-Proto` przyjmowany od pośrednika przed nginx (ingress/F5 musi go nadpisywać). |
| V4.2.1 | 2 | All application components (including load balancers, firewalls, and application servers) determine boundaries of incoming HTTP messages using the… | 🏢 | Granice wiadomości HTTP: nginx + Tomcat (standardowe); łańcuch z F5/ingress do potwierdzenia przy wdrożeniu. |
| V4.3.1 | 2 | A query allowlist, depth limiting, amount limiting, or query cost analysis is used to prevent GraphQL or data layer expression Denial of Service… | ➖ | Brak GraphQL. |
| V4.3.2 | 2 | GraphQL introspection queries are disabled in the production environment unless the GraphQL API is meant to be used by other parties. | ➖ | Brak GraphQL. |
| V4.4.1 | 1 | WebSocket over TLS (WSS) is used for all WebSocket connections. | ➖ | Brak WebSocket (aktualizacje na żywo przez SSE w ramach sesji HTTPS). |
| V4.4.2 | 2 | Verify that, during the initial HTTP WebSocket handshake, the Origin header field is checked against a list of origins allowed for the application. | ➖ | Brak WebSocket. |
| V4.4.3 | 2 | Verify that, if the application's standard session management cannot be used, dedicated tokens are being used for this, which comply with the… | ➖ | Brak WebSocket. |
| V4.4.4 | 2 | Dedicated WebSocket session management tokens are initially obtained or validated through the previously authenticated HTTPS session when… | ➖ | Brak WebSocket. |

### V5 File Handling

✅ 3 · ➖ 6

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V5.1.1 | 2 | The documentation defines the permitted file types, expected file extensions, and maximum size (including unpacked size) for each upload feature.… | ➖ | Brak wgrywania plików (jedynie pobieranie CSV). |
| V5.2.1 | 1 | The application will only accept files of a size which it can process without causing a loss of performance or a denial of service attack. | ✅ | Limity rozmiaru żądań: 1 MB (UI/API), 5 MB (ingest), 1000 alertów na żądanie. |
| V5.2.2 | 1 | When the application accepts a file, either on its own or within an archive such as a zip file, it checks if the file extension matches an… | ➖ | Brak wgrywania plików. |
| V5.2.3 | 2 | The application checks compressed files (e.g., zip, gz, docx, odt) against maximum allowed uncompressed size and against maximum number of files… | ➖ | Brak archiwów. |
| V5.3.1 | 1 | Files uploaded or generated by untrusted input and stored in a public folder, are not executed as server-side program code when accessed directly… | ➖ | Brak plików od użytkowników. |
| V5.3.2 | 1 | When the application creates file paths for file operations, instead of user-submitted filenames, it uses internally generated or trusted data, or… | ➖ | Brak operacji na plikach z nazw od użytkownika. |
| V5.4.1 | 2 | The application validates or ignores user-submitted filenames, including in a JSON, JSONP, or URL parameter and specifies a filename in the… | ✅ | Nazwa pliku CSV generowana przez serwer, `Content-Disposition: attachment`. |
| V5.4.2 | 2 | File names served (e.g., in HTTP response header fields or email attachments) are encoded or sanitized (e.g., following RFC 6266) to preserve… | ✅ | `ContentDisposition` Springa (RFC 6266). |
| V5.4.3 | 2 | Files obtained from untrusted sources are scanned by antivirus scanners to prevent serving of known malicious content. | ➖ | Brak plików z zewnątrz. |

### V6 Authentication

✅ 23 · 🟡 2 · ➖ 10

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V6.1.1 | 1 | Application documentation defines how controls such as rate limiting, anti-automation, and adaptive response, are used to defend against attacks… | ✅ | Sekcja A.3 (limity prób, blokady czasowe, limit na IP). |
| V6.1.2 | 2 | A list of context-specific words is documented in order to prevent their use in passwords. The list could include permutations of organization… | ✅ | Lista słów kontekstowych: `alerta.passwords.forbidden-words` (sekcja A.3); organizacja dopisuje nazwy firmy i systemów. |
| V6.1.3 | 2 | Verify that, if the application includes multiple authentication pathways, these are all documented together with the security controls and… | ✅ | Sekcja A.3: dwie ścieżki (konta lokalne, OIDC) i tryby `ENABLED / BREAK_GLASS_ONLY / DISABLED`. |
| V6.2.1 | 1 | User set passwords are at least 8 characters in length although a minimum of 15 characters is strongly recommended. | ✅ | Min. 12 znaków, 16 dla kont uprzywilejowanych (`PasswordPolicy`). |
| V6.2.2 | 1 | Users can change their password. | ✅ | Zmiana własnego hasła (`/api/v1/auth/password`). |
| V6.2.3 | 1 | Password change functionality requires the user's current and new password. | ✅ | Wymagane obecne i nowe hasło. |
| V6.2.4 | 1 | Passwords submitted during account registration or password change are checked against an available set of, at least, the top 3000 passwords which… | ✅ | Lista ~30 tys. popularnych haseł (SecLists top 1M, ≥ 12 znaków). |
| V6.2.5 | 1 | Passwords of any composition can be used, without rules limiting the type of characters permitted. There must be no requirement for a minimum… | ✅ | Brak reguł złożoności. |
| V6.2.6 | 1 | Password input fields use type=password to mask the entry. Applications may allow the user to temporarily view the entire masked password, or the… | ✅ | Pola `type=password`. |
| V6.2.7 | 1 | "paste" functionality, browser password helpers, and external password managers are permitted. | ✅ | Wklejanie i menedżery haseł dozwolone. |
| V6.2.8 | 1 | The application verifies the user's password exactly as received from the user, without any modifications such as truncation or case transformation. | ✅ | Hasło weryfikowane dokładnie (bez obcinania i zmiany wielkości liter). |
| V6.2.9 | 2 | Passwords of at least 64 characters are permitted. | ✅ | Do 128 znaków. |
| V6.2.10 | 2 | A user's password stays valid until it is discovered to be compromised or the user rotates it. The application must not require periodic… | ✅ | Brak wymuszonej okresowej zmiany. |
| V6.2.11 | 2 | The documented list of context specific words is used to prevent easy to guess passwords being created. | ✅ | Hasło z zakazanym słowem odrzucane (`CONTAINS_FORBIDDEN_WORD`), test `forbiddenWordsAreRefused`. |
| V6.2.12 | 2 | Passwords submitted during account registration or password changes are checked against a set of breached passwords. | 🟡 | Lista popularnych haseł z wycieków (offline); brak pełnej bazy wycieków typu HIBP (świadomie – brak połączeń na zewnątrz). |
| V6.3.1 | 1 | Controls to prevent attacks such as credential stuffing and password brute force are implemented according to the application's security… | ✅ | Blokada konta po 5 nieudanych próbach (15 min, podwajana do 1 h), limit na IP (20 / 15 min, w bazie – wspólny dla replik, próba rezerwowana przed sprawdzeniem hasła, więc równoległa seria nie przekroczy limitu) – `LoginThrottle`; adres klienta niepodrabialny (G1). |
| V6.3.2 | 1 | Default user accounts (e.g., "root", "admin", or "sa") are not present in the application or are disabled. | ✅ | Brak kont domyślnych – pierwszy administrator zakładany CLI z hasłem jednorazowym. |
| V6.3.3 | 2 | Either a multi-factor authentication mechanism or a combination of single-factor authentication mechanisms, must be used in order to access the… | 🟡 | MFA przez SSO (wymuszane u dostawcy, opcjonalnie `required-acr`); konta lokalne bez MFA – na produkcji tryb `BREAK_GLASS_ONLY` (luka G6). |
| V6.3.4 | 2 | Verify that, if the application includes multiple authentication pathways, there are no undocumented pathways and that security controls and… | ✅ | Brak nieudokumentowanych ścieżek; `LocalLoginPolicy` egzekwuje tryb także dla istniejących sesji. |
| V6.4.1 | 1 | System generated initial passwords or activation codes are securely randomly generated, follow the existing password policy, and expire after a… | ✅ | Hasła jednorazowe: CSPRNG, zgodne z polityką, jednorazowe i ważne 72 h (`alerta.passwords.one-time-validity`), test `oneTimePasswordsExpire`. |
| V6.4.2 | 1 | Password hints or knowledge-based authentication (so-called "secret questions") are not present. | ✅ | Brak podpowiedzi i pytań pomocniczych. |
| V6.4.3 | 2 | A secure process for resetting a forgotten password is implemented, that does not bypass any enabled multi-factor authentication mechanisms. | ✅ | Brak samoobsługowego resetu; reset tylko przez administratora dostępu (audytowany), SSO – u dostawcy. |
| V6.4.4 | 2 | If a multi-factor authentication factor is lost, evidence of identity proofing is performed at the same level as during enrollment. | ➖ | Brak MFA w aplikacji (MFA u dostawcy SSO). |
| V6.5.1 | 2 | Lookup secrets, out-of-band authentication requests or codes, and time-based one-time passwords (TOTPs) are only successfully usable once. | ➖ | Brak TOTP / kodów jednorazowych w aplikacji. |
| V6.5.2 | 2 | Verify that, when being stored in the application's backend, lookup secrets with less than 112 bits of entropy (19 random alphanumeric characters… | ➖ | j.w. |
| V6.5.3 | 2 | Lookup secrets, out-of-band authentication code, and time-based one-time password seeds, are generated using a Cryptographically Secure… | ➖ | j.w. |
| V6.5.4 | 2 | Lookup secrets and out-of-band authentication codes have a minimum of 20 bits of entropy (typically 4 random alphanumeric characters or 6 random… | ➖ | j.w. |
| V6.5.5 | 2 | Out-of-band authentication requests, codes, or tokens, as well as time-based one-time passwords (TOTPs) have a defined lifetime. Out of band… | ➖ | j.w. |
| V6.6.1 | 2 | Authentication mechanisms using the Public Switched Telephone Network (PSTN) to deliver One-time Passwords (OTPs) via phone or SMS are offered… | ➖ | Brak OTP przez SMS/telefon. |
| V6.6.2 | 2 | Out-of-band authentication requests, codes, or tokens are bound to the original authentication request for which they were generated and are not… | ➖ | j.w. |
| V6.6.3 | 2 | A code based out-of-band authentication mechanism is protected against brute force attacks by using rate limiting. Consider also using a code with… | ➖ | j.w. |
| V6.8.1 | 2 | Verify that, if the application supports multiple identity providers (IdPs), the user's identity cannot be spoofed via another supported identity… | ✅ | Konto SSO identyfikowane po `sub`; login zajęty przez konto lokalne jest odrzucany (SSO nie przejmuje kont). |
| V6.8.2 | 2 | The presence and integrity of digital signatures on authentication assertions (for example on JWTs or SAML assertions) are always validated,… | ✅ | Podpis ID tokenu weryfikowany kluczami z discovery dostawcy (Spring Security / Nimbus). |
| V6.8.3 | 2 | SAML assertions are uniquely processed and used only once within the validity period to prevent replay attacks. | ➖ | Brak SAML. |
| V6.8.4 | 2 | Verify that, if an application uses a separate Identity Provider (IdP) and expects specific authentication strength, methods, or recentness for… | ✅ | `required-acr` sprawdzane przy logowaniu SSO. |

### V7 Session Management

✅ 18

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V7.1.1 | 2 | The user's session inactivity timeout and absolute maximum session lifetime are documented, are appropriate in combination with other controls,… | ✅ | Sekcja A.4 (30 min admin / 8 h operator bezczynności, 12 h absolutnie, kiosk 30 dni – uzasadnienie). |
| V7.1.2 | 2 | The documentation defines how many concurrent (parallel) sessions are allowed for one account as well as the intended behaviors and actions to be… | ✅ | Sekcja A.4: bez limitu sesji równoległych (uzasadnienie: wiele ekranów dyżurnego, kiosk). |
| V7.1.3 | 2 | All systems that create and manage user sessions as part of a federated identity management ecosystem (such as SSO systems) are documented along… | ✅ | Sekcja A.4: sesja aplikacji niezależna od sesji SSO; wylogowanie kończy też sesję SSO (`end-session`). |
| V7.2.1 | 1 | The application performs all session token verification using a trusted, backend service. | ✅ | Sesja serwerowa (Spring Session JDBC), weryfikacja wyłącznie na serwerze. |
| V7.2.2 | 1 | The application uses either self-contained or reference tokens that are dynamically generated for session management, i.e. not using static API… | ✅ | Tokeny sesji generowane dynamicznie. |
| V7.2.3 | 1 | If reference tokens are used to represent user sessions, they are unique and generated using a cryptographically secure pseudo-random number… | ✅ | Identyfikator sesji: 32 bajty z SecureRandom (256 bitów, base64url) – `SessionCookies.sessionIdGenerator`. |
| V7.2.4 | 1 | The application generates a new session token on user authentication, including re-authentication, and terminates the current session token. | ✅ | Nowy identyfikator sesji przy logowaniu (`AuthController` – jawna rotacja), również po SSO. |
| V7.3.1 | 2 | There is an inactivity timeout such that re-authentication is enforced according to risk analysis and documented security decisions. | ✅ | `SessionPolicyFilter`: limity bezczynności wg uprawnień. |
| V7.3.2 | 2 | There is an absolute maximum session lifetime such that re-authentication is enforced according to risk analysis and documented security decisions. | ✅ | Limit absolutny 12 h (kiosk 30 dni). |
| V7.4.1 | 1 | When session termination is triggered (such as logout or expiration), the application disallows any further use of the session. For reference… | ✅ | Wylogowanie unieważnia sesję w bazie. |
| V7.4.2 | 1 | The application terminates all active sessions when a user account is disabled or deleted (such as an employee leaving the company). | ✅ | Wyłączenie, wygaśnięcie, reset hasła, zmiana kiosku – `terminateAll`. |
| V7.4.3 | 2 | The application gives the option to terminate all other active sessions after a successful change or removal of any authentication factor… | ✅ | Zmiana hasła kończy pozostałe sesje (`terminateOthers`). |
| V7.4.4 | 2 | All pages that require authentication have easy and visible access to logout functionality. | ✅ | Wylogowanie zawsze w menu użytkownika (górny pasek). |
| V7.4.5 | 2 | Application administrators are able to terminate active sessions for an individual user or for all users. | ✅ | Administrator dostępu: „Zakończ sesje” użytkownika (`/users/{id}/terminate-sessions`). |
| V7.5.1 | 2 | The application requires full re-authentication before allowing modifications to sensitive account attributes which may affect authentication such… | ✅ | Użytkownik nie zmienia sam atrybutów logowania poza hasłem (wymaga obecnego hasła); dane z SSO pochodzą od dostawcy. |
| V7.5.2 | 2 | Users are able to view and (having authenticated again with at least one factor) terminate any or all currently active sessions. | ✅ | „Moje sesje” w profilu (0.37.0, G8): przeglądarka, adres, od kiedy, ostatnia aktywność; zakończenie jednej lub wszystkich innych – konto lokalne podaje hasło ponownie, konto SSO musi w ciągu 10 min ponownie podać poświadczenia dostawcy (0.39.1: logowanie z `prompt=login` i `max_age=0`, liczy się tylko `auth_time` z tokenu ID mieszczący się w tym logowaniu – ciche logowanie na żywej sesji Keycloaka się nie liczy; test z prawdziwym Keycloakiem i tą samą przeglądarką); identyfikator sesji nie opuszcza serwera (skrót SHA-256); audyt `auth.session.end`; testy `MySessionsTest`, `SingleSignOnTest`. |
| V7.6.1 | 2 | Session lifetime and termination between Relying Parties (RPs) and Identity Providers (IdPs) behave as documented, requiring re-authentication as… | ✅ | Sekcja A.4: sesja aplikacji ma własne limity niezależnie od SSO. |
| V7.6.2 | 2 | Creation of a session requires either the user's consent or an explicit action, preventing the creation of new application sessions without user… | ✅ | Sesja SSO powstaje tylko po kliknięciu „Zaloguj przez SSO”. |

### V8 Authorization

✅ 6 · ➖ 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V8.1.1 | 1 | Authorization documentation defines rules for restricting function-level and data-specific access based on consumer permissions and resource… | ✅ | Sekcja A.5 + instrukcja wdrożenia, rozdział 2 (role per środowisko, uprawnienia globalne). |
| V8.1.2 | 2 | Authorization documentation defines rules for field-level access restrictions (both read and write) based on consumer permissions and resource… | ✅ | Sekcja A.5: brak ograniczeń na poziomie pól poza sekretami (nigdy nie zwracane). |
| V8.2.1 | 1 | The application ensures that function-level access is restricted to consumers with explicit permissions. | ✅ | `denyAll` domyślnie, `@PreAuthorize` na każdym punkcie końcowym; testy dostępu. |
| V8.2.2 | 1 | The application ensures that data-specific access is restricted to consumers with explicit permissions to specific data items to mitigate insecure… | ✅ | Filtry środowisk w zapytaniach, `readable(id)` → 404 dla cudzych obiektów; testy regresji (np. oś czasu, heartbeaty). |
| V8.2.3 | 2 | The application ensures that field-level access is restricted to consumers with explicit permissions to specific fields to mitigate broken object… | ✅ | Odpowiedzi to dedykowane rekordy (bez skrótów haseł, kluczy, sekretów). |
| V8.3.1 | 1 | The application enforces authorization rules at a trusted service layer and doesn't rely on controls that an untrusted consumer could manipulate,… | ✅ | Autoryzacja zawsze na serwerze; UI tylko ukrywa. |
| V8.4.1 | 2 | Multi-tenant applications use cross-tenant controls to ensure consumer operations will never affect tenants with which they do not have… | ➖ | Aplikacja nie jest wielodostępna (jedna organizacja; środowiska to nie najemcy). |

### V9 Self-contained Tokens

✅ 6 · 🏢 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V9.1.1 | 1 | Self-contained tokens are validated using their digital signature or MAC to protect against tampering before accepting the token's contents. | ✅ | Jedyny token samowystarczalny: ID token OIDC – podpis weryfikowany. |
| V9.1.2 | 1 | Only algorithms on an allowlist can be used to create and verify self-contained tokens, for a given context. The allowlist must include the… | ✅ | Algorytmy z metadanych dostawcy (RS256/ES256) przez Nimbus; `none` odrzucane. |
| V9.1.3 | 1 | Key material that is used to validate self-contained tokens is from trusted pre-configured sources for the token issuer, preventing attackers from… | ✅ | Klucze tylko z `jwks_uri` skonfigurowanego wystawcy (discovery z weryfikacją `issuer`). |
| V9.2.1 | 1 | Verify that, if a validity time span is present in the token data, the token and its content are accepted only if the verification time is within… | ✅ | `exp`/`iat` sprawdzane przez Spring Security. |
| V9.2.2 | 2 | The service receiving a token validates the token to be the correct type and is meant for the intended purpose before accepting the token's… | ✅ | Używany wyłącznie ID token do uwierzytelnienia; access token nie służy do autoryzacji w aplikacji. |
| V9.2.3 | 2 | The service only accepts tokens which are intended for use with that service (audience). For JWTs, this can be achieved by validating the 'aud'… | ✅ | `aud` = `client-id` sprawdzane. |
| V9.2.4 | 2 | Verify that, if a token issuer uses the same private key for issuing tokens to different audiences, the issued tokens contain an audience… | 🏢 | Odbiorca w tokenach – konfiguracja dostawcy SSO. |

### V10 OAuth and OIDC

✅ 9 · 🏢 13 · ➖ 7

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V10.1.1 | 2 | Tokens are only sent to components that strictly need them. For example, when using a backend-for-frontend pattern for browser-based JavaScript… | ✅ | Wzorzec BFF: tokeny tylko na serwerze, przeglądarka ma wyłącznie cookie sesji. |
| V10.1.2 | 2 | The client only accepts values from the authorization server (such as the authorization code or ID Token) if these values result from an… | ✅ | `state` powiązany z sesją przeglądarki, PKCE, nonce. |
| V10.2.1 | 2 | Verify that, if the code flow is used, the OAuth client has protection against browser-based request forgery attacks, commonly known as cross-site… | ✅ | PKCE + `state`. |
| V10.2.2 | 2 | Verify that, if the OAuth client can interact with more than one authorization server, it has a defense against mix-up attacks. For example, it… | ➖ | Jeden serwer autoryzacji. |
| V10.3.1 | 2 | The resource server only accepts access tokens that are intended for use with that service (audience). The audience may be included in a… | ➖ | Aplikacja nie jest serwerem zasobów dla tokenów OAuth. |
| V10.3.2 | 2 | The resource server enforces authorization decisions based on claims from the access token that define delegated authorization. If claims such as… | ➖ | j.w. |
| V10.3.3 | 2 | If an access control decision requires identifying a unique user from an access token (JWT or related token introspection response), the resource… | ➖ | j.w. |
| V10.3.4 | 2 | Verify that, if the resource server requires specific authentication strength, methods, or recentness, it verifies that the presented access token… | ➖ | j.w. |
| V10.4.1 | 1 | The authorization server validates redirect URIs based on a client-specific allowlist of pre-registered URIs using exact string comparison. | 🏢 | Serwer autoryzacji (Keycloak/Entra ID): dokładne adresy przekierowań – konfiguracja klienta przy wdrożeniu. |
| V10.4.2 | 1 | Verify that, if the authorization server returns the authorization code in the authorization response, it can be used only once for a token… | 🏢 | Serwer autoryzacji. |
| V10.4.3 | 1 | The authorization code is short-lived. The maximum lifetime can be up to 10 minutes for L1 and L2 applications and up to 1 minute for L3 applications. | 🏢 | Serwer autoryzacji. |
| V10.4.4 | 1 | For a given client, the authorization server only allows the usage of grants that this client needs to use. Note that the grants 'token' (Implicit… | 🏢 | Serwer autoryzacji: klient tylko z `authorization_code`. |
| V10.4.5 | 1 | The authorization server mitigates refresh token replay attacks for public clients, preferably using sender-constrained refresh tokens, i.e.,… | ➖ | Klient poufny, bez tokenów odświeżania w przeglądarce. |
| V10.4.6 | 2 | Verify that, if the code grant is used, the authorization server mitigates authorization code interception attacks by requiring proof key for code… | 🏢 | Serwer autoryzacji wymaga PKCE (klient go wysyła). |
| V10.4.7 | 2 | If the authorization server supports unauthenticated dynamic client registration, it mitigates the risk of malicious client applications. It must… | 🏢 | Serwer autoryzacji. |
| V10.4.8 | 2 | Refresh tokens have an absolute expiration, including if sliding refresh token expiration is applied. | 🏢 | Serwer autoryzacji. |
| V10.4.9 | 2 | Refresh tokens and reference access tokens can be revoked by an authorized user using the authorization server user interface, to mitigate the… | 🏢 | Serwer autoryzacji. |
| V10.4.10 | 2 | Confidential client is authenticated for client-to-authorized server backchannel requests such as token requests, pushed authorization requests… | ✅ | Klient poufny uwierzytelnia się sekretem (z Secret/Vault). |
| V10.4.11 | 2 | The authorization server configuration only assigns the required scopes to the OAuth client. | ✅ | Zakresy: `openid profile email` (konfigurowalne). |
| V10.5.1 | 2 | The client (as the relying party) mitigates ID Token replay attacks. For example, by ensuring that the 'nonce' claim in the ID Token matches the… | ✅ | `nonce` sprawdzany. |
| V10.5.2 | 2 | The client uniquely identifies the user from ID Token claims, usually the 'sub' claim, which cannot be reassigned to other users (for the scope of… | ✅ | Użytkownik po `sub`. |
| V10.5.3 | 2 | The client rejects attempts by a malicious authorization server to impersonate another authorization server through authorization server metadata.… | ✅ | Metadane muszą opisywać skonfigurowanego wystawcę (`OidcProvider`: porównanie `issuer`). |
| V10.5.4 | 2 | The client validates that the ID Token is intended to be used for that client (audience) by checking that the 'aud' claim from the token is equal… | ✅ | `aud` = `client_id`. |
| V10.5.5 | 2 | Verify that, when using OIDC back-channel logout, the relying party mitigates denial of service through forced logout and cross-JWT confusion in… | ➖ | Brak back-channel logout. |
| V10.6.1 | 2 | The OpenID Provider only allows values 'code', 'ciba', 'id_token', or 'id_token code' for response mode. Note that 'code' is preferred over… | 🏢 | Dostawca OIDC. |
| V10.6.2 | 2 | The OpenID Provider mitigates denial of service through forced logout. By obtaining explicit confirmation from the end-user or, if present,… | 🏢 | Dostawca OIDC. |
| V10.7.1 | 2 | The authorization server ensures that the user consents to each authorization request. If the identity of the client cannot be assured, the… | 🏢 | Dostawca OIDC (zgody). |
| V10.7.2 | 2 | When the authorization server prompts for user consent, it presents sufficient and clear information about what is being consented to. When… | 🏢 | Dostawca OIDC. |
| V10.7.3 | 2 | The user can review, modify, and revoke consents which the user has granted through the authorization server. | 🏢 | Dostawca OIDC. |

### V11 Cryptography

✅ 8 · 🟡 1 · ➖ 5

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V11.1.1 | 2 | There is a documented policy for management of cryptographic keys and a cryptographic key lifecycle that follows a key management standard such as… | 🟡 | Klucze i sekrety z Secret/Vault (sekcja A.6); brak formalnej polityki cyklu życia kluczy wg NIST SP 800-57 – po stronie organizacji (luka G10). |
| V11.1.2 | 2 | A cryptographic inventory is performed, maintained, regularly updated, and includes all cryptographic keys, algorithms, and certificates used by… | ✅ | Inwentarz kryptografii: sekcja A.6. |
| V11.2.1 | 2 | Industry-validated implementations (including libraries and hardware-accelerated implementations) are used for cryptographic operations. | ✅ | JDK (JCA), Spring Security (Argon2 przez Bouncy Castle), Nimbus – biblioteki przemysłowe. |
| V11.2.2 | 2 | The application is designed with crypto agility such that random number, authenticated encryption, MAC, or hashing algorithms, key lengths,… | ✅ | Algorytmy w jednym miejscu (`PasswordConfig`, `ApiKeyService`); Argon2 z możliwością zmiany parametrów (DelegatingPasswordEncoder). |
| V11.2.3 | 2 | All cryptographic primitives utilize a minimum of 128-bits of security based on the algorithm, key size, and configuration. For example, a 256-bit… | ✅ | ≥ 128 bitów: SHA-256, Argon2id, klucze API ~238 bitów, TLS wg konfiguracji JDK. |
| V11.3.1 | 1 | Insecure block modes (e.g., ECB) and weak padding schemes (e.g., PKCS#1 v1.5) are not used. | ➖ | Aplikacja nie szyfruje danych samodzielnie (TLS przez JDK/ingress). |
| V11.3.2 | 1 | Only approved ciphers and modes such as AES with GCM are used. | ➖ | j.w. |
| V11.3.3 | 2 | Encrypted data is protected against unauthorized modification preferably by using an approved authenticated encryption method or by combining an… | ➖ | j.w. |
| V11.4.1 | 1 | Only approved hash functions are used for general cryptographic use cases, including digital signatures, HMAC, KDF, and random bit generation.… | ✅ | SHA-256 (klucze API), bez MD5/SHA-1 w logice bezpieczeństwa. |
| V11.4.2 | 2 | Passwords are stored using an approved, computationally intensive, key derivation function (also known as a "password hashing function"), with… | ✅ | Argon2id (parametry Spring Security 5.8+ zgodne z OWASP). |
| V11.4.3 | 2 | Hash functions used in digital signatures, as part of data authentication or data integrity are collision resistant and have appropriate… | ✅ | SHA-256. |
| V11.4.4 | 2 | The application uses approved key derivation functions with key stretching parameters when deriving secret keys from passwords. The parameters in… | ➖ | Brak wyprowadzania kluczy z haseł. |
| V11.5.1 | 2 | All random numbers and strings which are intended to be non-guessable must be generated using a cryptographically secure pseudo-random number… | ✅ | `SecureRandom` dla kluczy API (40 znaków z 62 ≈ 238 bitów) i haseł jednorazowych; identyfikatory sesji z SecureRandom. |
| V11.6.1 | 2 | Only approved cryptographic algorithms and modes of operation are used for key generation and seeding, and digital signature generation and… | ➖ | Aplikacja nie generuje kluczy ani podpisów. |

### V12 Secure Communication

✅ 2 · 🟡 2 · 🏢 4 · ➖ 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V12.1.1 | 1 | Only the latest recommended versions of the TLS protocol are enabled, such as TLS 1.2 and TLS 1.3. The latest version of the TLS protocol must be… | 🏢 | TLS kończony na ingress/F5 – TLS 1.2/1.3 w konfiguracji organizacji; połączenia wychodzące przez JDK 25 (domyślnie TLS 1.2+). |
| V12.1.2 | 2 | Only recommended cipher suites are enabled, with the strongest cipher suites set as preferred. L3 applications must only support cipher suites… | 🏢 | Szyfry na ingress/F5; JDK 25 – domyślne bezpieczne zestawy. |
| V12.1.3 | 2 | The application validates that mTLS client certificates are trusted before using the certificate identity for authentication or authorization. | ➖ | Brak mTLS w aplikacji (w siatce Istio – po stronie platformy). |
| V12.2.1 | 1 | TLS is used for all connectivity between a client and external facing, HTTP-based services, and does not fall back to insecure or unencrypted… | 🏢 | HTTPS wymagany (cookie `Secure`); TLS na ingress/F5. |
| V12.2.2 | 1 | External facing services use publicly trusted TLS certificates. | 🏢 | Certyfikat publicznie zaufany lub z firmowego CA – po stronie organizacji. |
| V12.3.1 | 2 | An encrypted protocol such as TLS is used for all inbound and outbound connections to and from the application, including monitoring systems,… | 🟡 | Do Alertmanagera, SSO i bazy TLS możliwy (`ca-file`, `sslmode=verify-full`); wewnątrz poda/klastra (ingress → frontend → backend) HTTP, chyba że siatka mTLS (Istio ambient) – luka G9. |
| V12.3.2 | 2 | TLS clients validate certificates received before communicating with a TLS server. | ✅ | Klient HTTP weryfikuje certyfikaty; `insecure-skip-verify` tylko jawnie w konfiguracji (ostrzeżenie w logu). |
| V12.3.3 | 2 | TLS or another appropriate transport encryption mechanism used for all connectivity between internal, HTTP-based services within the application,… | 🟡 | Jak V12.3.1 (luka G9). |
| V12.3.4 | 2 | TLS connections between internal services use trusted certificates. Where internally generated or self-signed certificates are used, the consuming… | ✅ | Własne CA (`internalCA` / `ca-file`) zaufane tylko dla wskazanych połączeń. |

### V13 Configuration

✅ 10 · 🟡 2 · 🏢 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V13.1.1 | 2 | All communication needs for the application are documented. This must include external services which the application relies upon and cases where… | ✅ | Sekcja A.7 (komunikacja) + dokumentacja wdrożenia (polityki sieciowe). |
| V13.2.1 | 2 | Communications between backend application components that don't support the application's standard user session mechanism, including APIs,… | 🟡 | Baza: login i hasło; Alertmanager: token/basic; frontend → backend w obrębie klastra bez uwierzytelnienia (ogranicza NetworkPolicy/siatka) – luka G9. |
| V13.2.2 | 2 | Communications between backend application components, including local or operating system services, APIs, middleware, and data layers, are… | ✅ | Osobne konto do migracji i konto aplikacji tylko z DML (wariant B w dokumentacji). |
| V13.2.3 | 2 | If a credential has to be used for service authentication, the credential being used by the consumer is not a default credential (e.g., root/root… | ✅ | Brak domyślnych haseł – wymagane przy instalacji (Helm odmawia bez hasła). |
| V13.2.4 | 2 | An allowlist is used to define the external resources or systems with which the application is permitted to communicate (e.g., for outbound… | ✅ | Połączenia wychodzące tylko do adresów z konfiguracji (Alertmanagery, OIDC, baza). |
| V13.2.5 | 2 | The web or application server is configured with an allowlist of resources or systems to which the server can send requests or load data or files… | 🟡 | Allowlista w konfiguracji aplikacji; na poziomie sieci – NetworkPolicy (opcjonalne, domyślnie wyłączone). |
| V13.3.1 | 2 | A secrets management solution, such as a key vault, is used to securely create, store, control access to, and destroy backend secrets. These could… | ✅ | Sekrety z Kubernetes Secret, `existingSecret` albo HashiCorp Vault przez CSI (tryb `csi`, bez kopii w etcd). |
| V13.3.2 | 2 | Access to secret assets adheres to the principle of least privilege. | 🏢 | Polityka Vault i RBAC – po stronie organizacji (dokumentacja podaje minimalną politykę read-only). |
| V13.4.1 | 1 | The application is deployed either without any source control metadata, including the .git or .svn folders, or in a way that these folders are… | ✅ | Obrazy bez `.git` (budowane z kontekstu, `.dockerignore`). |
| V13.4.2 | 2 | Debug modes are disabled for all components in production environments to prevent exposure of debugging features and information leakage. | ✅ | Brak trybów debug; `include-stacktrace: never`. |
| V13.4.3 | 2 | Web servers do not expose directory listings to clients unless explicitly intended. | ✅ | nginx bez `autoindex`. |
| V13.4.4 | 2 | Using the HTTP TRACE method is not supported in production environments, to avoid potential information leakage. | ✅ | TRACE wyłączony (Tomcat domyślnie, nginx nie obsługuje). |
| V13.4.5 | 2 | Documentation (such as for internal APIs) and monitoring endpoints are not exposed unless explicitly intended. | ✅ | Actuator tylko `health, prometheus` na osobnym porcie 8081, niepublikowanym przez ingress; brak Swaggera. |

### V14 Data Protection

✅ 9

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V14.1.1 | 2 | All sensitive data created and processed by the application has been identified and classified into protection levels. This includes data that is… | ✅ | Klasyfikacja danych: sekcja A.8. |
| V14.1.2 | 2 | All sensitive data protection levels have a documented set of protection requirements. This must include (but not be limited to) requirements… | ✅ | Wymagania ochrony per klasa: sekcja A.8. |
| V14.2.1 | 1 | Sensitive data is only sent to the server in the HTTP message body or header fields, and that the URL and query string do not contain sensitive… | ✅ | Klucze API w nagłówku `Authorization`, sesja w cookie; nic wrażliwego w URL. |
| V14.2.2 | 2 | The application prevents sensitive data from being cached in server components, such as load balancers and application caches, or ensures that the… | ✅ | `Cache-Control: no-store` na API (Spring Security) i stronie głównej. |
| V14.2.3 | 2 | Defined sensitive data is not sent to untrusted parties (e.g., user trackers) to prevent unwanted collection of data outside of the application's… | ✅ | Brak narzędzi śledzących i zasobów zewnętrznych (CSP `default-src 'self'`). |
| V14.2.4 | 2 | Controls around sensitive data related to encryption, integrity verification, retention, how the data is to be logged, access controls around… | ✅ | Sekcja A.8 (retencja, logowanie, dostęp). |
| V14.3.1 | 1 | Authenticated data is cleared from client storage, such as the browser DOM, after the client or session is terminated. The 'Clear-Site-Data' HTTP… | ✅ | Wylogowanie: sesja unieważniona na serwerze, `Clear-Site-Data: "cache", "storage"`, pełne przeładowanie strony (G3). |
| V14.3.2 | 2 | The application sets sufficient anti-caching HTTP response header fields (i.e., Cache-Control: no-store) so that sensitive data is not cached in… | ✅ | `Cache-Control: no-store` na odpowiedziach API i `index.html`. |
| V14.3.3 | 2 | Data stored in browser storage (such as localStorage, sessionStorage, IndexedDB, or cookies) does not contain sensitive data, with the exception… | ✅ | W localStorage tylko preferencje (język, motyw, gęstość). |

### V15 Secure Coding and Architecture

✅ 12 · 🟡 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V15.1.1 | 1 | Application documentation defines risk based remediation time frames for 3rd party component versions with vulnerabilities and for updating… | ✅ | Terminy usuwania podatności i aktualizacji: sekcja A.10. |
| V15.1.2 | 2 | An inventory catalog, such as software bill of materials (SBOM), is maintained of all third-party libraries in use, including verifying that… | ✅ | SBOM CycloneDX w każdym obrazie: backend `META-INF/sbom/application.cdx.json` w jarze, frontend `/usr/share/sbom/alerta-next-frontend.cdx.json`. |
| V15.1.3 | 2 | The application documentation identifies functionality which is time-consuming or resource-demanding. This must include how to prevent a loss of… | ✅ | Sekcja A.2 (funkcje kosztowne: eksport, oś czasu, raporty) + test obciążeniowy (`load/`). |
| V15.2.1 | 1 | The application only contains components which have not breached the documented update and remediation time frames. | 🟡 | Zależności aktualne (Angular 22, Spring Boot 4.1, Java 25); zgodność z terminami A.10 wymaga cyklicznego skanu SBOM (np. Trivy w rejestrze) – proces po stronie organizacji. |
| V15.2.2 | 2 | The application has implemented defenses against loss of availability due to functionality which is time-consuming or resource-demanding, based on… | ✅ | Limity (A.2), stronicowanie, limity okien, pula połączeń, test obciążeniowy 10× awarii. |
| V15.2.3 | 2 | The production environment only includes functionality that is required for the application to function, and does not expose extraneous… | ✅ | Obraz produkcyjny bez kodu testowego; brak punktów diagnostycznych. |
| V15.3.1 | 1 | The application only returns the required subset of fields from a data object. For example, it should not return an entire data object, as some… | ✅ | Dedykowane rekordy odpowiedzi (np. `ApiKeyView` bez skrótu, `SystemStatus` z sekretami tylko „ustawione/brak”). |
| V15.3.2 | 2 | Where the application backend makes calls to external URLs, it is configured to not follow redirects unless it is intended functionality. | ✅ | Klient HTTP (`HttpClients`) bez podążania za przekierowaniami (domyślnie `NEVER`). |
| V15.3.3 | 2 | The application has countermeasures to protect against mass assignment attacks by limiting allowed fields per controller and action, e.g., it is… | ✅ | Żądania jako rekordy z jawnymi polami (brak wiązania encji z JSON). |
| V15.3.4 | 2 | All proxying and middleware components transfer the user's original IP address correctly using trusted data fields that cannot be manipulated by… | ✅ | Adres klienta: moduł realip nginx ufa `X-Forwarded-For` tylko od adresów z `TRUSTED_PROXIES` i przekazuje backendowi jedną wartość; bez listy liczy się bezpośrednie połączenie. Test `e2e/client-ip-check.sh` (G1). Wdrożenie musi ustawić `TRUSTED_PROXIES`. |
| V15.3.5 | 2 | The application explicitly ensures that variables are of the correct type and performs strict equality and comparator operations. This is to avoid… | ✅ | Java statycznie typowana; TypeScript `strict`. |
| V15.3.6 | 2 | JavaScript code is written in a way that prevents prototype pollution, for example, by using Set() or Map() instead of object literals. | ✅ | Brak scalania obiektów z danych; `Map`/`Set` w logice UI. |
| V15.3.7 | 2 | The application has defenses against HTTP parameter pollution attacks, particularly if the application framework makes no distinction about the… | ✅ | Parametry filtrów tylko z query string, jawnie nazwane; ciało żądań jako JSON. |

### V16 Security Logging and Error Handling

✅ 15 · 🏢 1

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V16.1.1 | 2 | An inventory exists documenting the logging performed at each layer of the application's technology stack, what events are being logged, log… | ✅ | Inwentarz logów: sekcja A.9. |
| V16.2.1 | 2 | Each log entry includes necessary metadata (such as when, where, who, what) that would allow for a detailed investigation of the timeline when an… | ✅ | Kto (użytkownik/klucz), co (akcja), kiedy (UTC), skąd (IP, identyfikator żądania) w audycie i logu żądań. |
| V16.2.2 | 2 | Time sources for all logging components are synchronized, and that timestamps in security event metadata use UTC or include an explicit time zone… | ✅ | Znaczniki czasu w UTC (ECS `@timestamp`, konsola z `Z`); synchronizacja zegarów – NTP węzłów. |
| V16.2.3 | 2 | The application only stores or broadcasts logs to the files and services that are documented in the log inventory. | ✅ | Logi tylko na stdout i do pliku JSON (sekcja A.9). |
| V16.2.4 | 2 | Logs can be read and correlated by the log processor that is in use, preferably by using a common logging format. | ✅ | Elastic Common Schema (JSON). |
| V16.2.5 | 2 | When logging sensitive data, the application enforces logging based on the data's protection level. For example, it may not be allowed to log… | ✅ | Log żądania: metoda, ścieżka, status, czas, użytkownik, IP, identyfikator – bez treści i nagłówków; hasła, klucze i tokeny nie są logowane; w konfiguracji na „Stanie systemu” sekrety tylko jako „ustawione/brak”, dane logowania w URL maskowane. |
| V16.3.1 | 2 | All authentication operations are logged, including successful and unsuccessful attempts. Additional metadata, such as the type of authentication… | ✅ | Logowania udane i nieudane w audycie (`auth.login`, powód, IP), SSO również. |
| V16.3.2 | 2 | Failed authorization attempts are logged. For L3, this must include logging all authorization decisions, including logging when sensitive data is… | ✅ | Odmowa dostępu → wpis `access.denied` w audycie. |
| V16.3.3 | 2 | The application logs the security events that are defined in the documentation and also logs attempts to bypass the security controls, such as… | ✅ | Odrzucony token CSRF zalogowanego użytkownika → `security.csrf_rejected` w audycie (anonimowe tylko w logu); odmowy dostępu, logowania, blokady – w audycie. |
| V16.3.4 | 2 | The application logs unexpected errors and security control failures such as backend TLS failures. | ✅ | Nieoczekiwane błędy z identyfikatorem żądania; błędy połączeń z Alertmanagerem/SSO w logu i na „Stanie systemu”. |
| V16.4.1 | 2 | All logging components appropriately encode data to prevent log injection. | ✅ | Format JSON (ECS) koduje dane; w logu tekstowym wartości z zewnątrz (login, nazwa alertu) bez znaków sterujących (`LogSafe`). |
| V16.4.2 | 2 | Logs are protected from unauthorized access and cannot be modified. | ✅ | Audyt append-only (wyzwalacz w bazie blokuje UPDATE/DELETE/TRUNCATE); dostęp tylko dla Audytora. Od 0.46.0 łańcuch skrótów SHA-256 (`audit_chain`, decyzja 139) – zmiana, usunięcie lub przestawienie wpisu także przez właściciela bazy jest wykrywalne; od 0.47.0 kotwice co godzinę w logu (ELK), sprawdzenie co noc z metryką `alerta_audit_chain_ok` i `alerta-admin verify-audit` z kotwicami (obcięta końcówka); od 0.55.0 status nie jest OK, gdy starsze wpisy są poza łańcuchem (`alerta_audit_chain_orphaned`), a nocne sprawdzenie najpierw je dołącza. |
| V16.4.3 | 2 | Logs are securely transmitted to a logically separate system for analysis, detection, alerting, and escalation. The aim is to ensure that if the… | 🏢 | Logi (w tym zdarzenia audytu) w JSON do ELK/SIEM – konfiguracja agenta po stronie organizacji. |
| V16.5.1 | 2 | A generic message is returned to the consumer when an unexpected or security-sensitive error occurs, ensuring no exposure of sensitive internal… | ✅ | Ogólne komunikaty (`problem+json` z kodem), bez stosu wywołań; identyfikator żądania do zgłoszenia. |
| V16.5.2 | 2 | The application continues to operate securely when external resource access fails, for example, by using patterns such as circuit breakers or… | ✅ | Niedostępny Alertmanager/SSO: łagodna degradacja (wyciszenia niedostępne z komunikatem, synchronizacja pomija, lista działa). |
| V16.5.3 | 2 | The application fails gracefully and securely, including when an exception occurs, preventing fail-open conditions such as processing a… | ✅ | Błędy kończą operację (transakcja wycofana), brak „fail-open” – np. sync wyciszeń nie odcisza przy awarii. |

### V17 WebRTC

➖ 7

| Id | L | Wymaganie | Status | Uzasadnienie |
|---|---|---|---|---|
| V17.1.1 | 2 | The Traversal Using Relays around NAT (TURN) service only allows access to IP addresses that are not reserved for special purposes (e.g., internal… | ➖ | Brak WebRTC. |
| V17.2.1 | 2 | The key for the Datagram Transport Layer Security (DTLS) certificate is managed and protected based on the documented policy for management of… | ➖ | Brak WebRTC. |
| V17.2.2 | 2 | The media server is configured to use and support approved Datagram Transport Layer Security (DTLS) cipher suites and a secure protection profile… | ➖ | Brak WebRTC. |
| V17.2.3 | 2 | Secure Real-time Transport Protocol (SRTP) authentication is checked at the media server to prevent Real-time Transport Protocol (RTP) injection… | ➖ | Brak WebRTC. |
| V17.2.4 | 2 | The media server is able to continue processing incoming media traffic when encountering malformed Secure Real-time Transport Protocol (SRTP) packets. | ➖ | Brak WebRTC. |
| V17.3.1 | 2 | The signaling server is able to continue processing legitimate incoming signaling messages during a flood attack. This should be achieved by… | ➖ | Brak WebRTC. |
| V17.3.2 | 2 | The signaling server is able to continue processing legitimate signaling messages when encountering malformed signaling message that could cause a… | ➖ | Brak WebRTC. |

---

## Część C – luki i plan

| # | Luka | Wymagania | Ryzyko | Działanie | Koszt |
|---|---|---|---|---|---|
| **G1** ✅ | **Adres klienta z `X-Forwarded-For` – zaufanie do wszystkich adresów prywatnych.** nginx dokleja nagłówek do wartości od klienta, a Tomcat (RemoteIpValve, domyślnie) uznaje za pośredników wszystkie adresy 10.x/172.16.x/192.168.x. W sieci firmowej klienci też mają adresy prywatne, więc podany przez nich `X-Forwarded-For` staje się „adresem klienta”. | V15.3.4, V4.1.3, V6.3.1 | **Średnie:** obejście limitu prób logowania na IP (blokada konta działa dalej), fałszywy IP w audycie | Zaufać tylko własnym pośrednikom: nginx ustawia `X-Forwarded-For` na adres, z którego sam dostał połączenie (lub moduł realip z listą zaufanych adresów ingress), a backend (`server.tomcat.remoteip.internal-proxies`) ufa tylko adresowi frontendu; parametr w Helm/manifestach dla adresów ingress/F5; test regresji | mały |
| **G2** ✅ | Ciasteczka bez prefiksu `__Host-`; identyfikator sesji 122 bity (UUID v4) zamiast ≥ 128 | V3.3.1, V3.3.3, V7.2.3 | Niskie (Secure, HttpOnly, SameSite=Strict już są) | `__Host-SESSION`, `__Host-XSRF-TOKEN` (Angular: nazwa cookie w `withXsrfConfiguration`); własny generator identyfikatora sesji (256 bitów, base64url); test `HttpServerSecurityTest`. Uwaga: zmiana nazwy cookie wyloguje wszystkich przy wdrożeniu | mały |
| **G3** ✅ | Po wylogowaniu dane mogą zostać w pamięci karty | V14.3.1 | Niskie (współdzielone stanowiska) | `Clear-Site-Data: "cache", "storage"` na wylogowaniu + pełne przeładowanie strony po wylogowaniu | mały |
| **G4** ✅ | Brak listy słów kontekstowych w hasłach (dziś tylko login) | V6.1.2, V6.2.11 | Niskie | Konfigurowalna lista `alerta.passwords.forbidden-words` (domyślnie nazwa aplikacji; organizacja dopisuje nazwę firmy, systemów) – porównanie bez wielkości liter | mały |
| **G5** | Brak ogólnego limitu częstotliwości żądań API (poza logowaniem i limitem alertów w żądaniu) | V2.4.1 | Niskie (tylko zalogowani / klucze API) | Limit na ingress (NGINX `limit-rps`) – zalecenie we wdrożeniu; ew. limit per klucz API w aplikacji | mały (konfiguracja) |
| **G6** | Konta lokalne bez MFA | V6.3.3 | Średnie, jeśli konta lokalne są używane na co dzień | Produkcja: SSO z MFA + `BREAK_GLASS_ONLY` (konta awaryjne w sejfie, każde logowanie w audycie i alert). TOTP dla kont lokalnych – tylko gdy organizacja tego zażąda | konfiguracja / duży (TOTP) |
| **G7** ✅ | Hasło jednorazowe bez terminu ważności | V6.4.1 | Niskie | Ważność np. 72 h od wydania; po terminie logowanie odrzucone, administrator wydaje nowe | mały |
| **G8** ✅ | Użytkownik nie widzi i nie kończy własnych sesji | V7.5.2 | Niskie | „Moje sesje” w profilu (urządzenie/przeglądarka, IP, od kiedy) z „zakończ inne” | średni |
| **G9** | Ruch wewnątrz klastra (ingress → frontend → backend) po HTTP | V12.3.1, V12.3.3, V13.2.1 | Zależne od platformy | Siatka mTLS (Istio ambient – sprawdzone na klastrze testowym) albo TLS na ingress→frontend; NetworkPolicy (`networkPolicy.enabled`) | wdrożenie |
| **G10** | Polityka cyklu życia kluczy (NIST SP 800-57) | V11.1.1 | Procesowe | Rotacja sekretów (baza, klucze API – ważność ≤ 2 lata, sekret OIDC) w procedurach organizacji / Vault | proces |
| **G11** ✅ | Brak SBOM i terminów aktualizacji zależności | V15.1.1, V15.1.2, V15.2.1 | Procesowe | SBOM CycloneDX (backend: wtyczka Gradle, frontend: `npm sbom`) przy każdym wydaniu; terminy: krytyczne 7 dni, wysokie 30 dni, pozostałe przy kolejnym wydaniu; przegląd zależności raz w miesiącu | mały |
| **G12** ✅ | Nie wszystkie próby obejścia kontroli są osobnymi zdarzeniami bezpieczeństwa; w tekstowym formacie konsoli możliwe wstrzyknięcie nowej linii (nazwy alertów od nadawców) | V16.3.3, V16.4.1 | Niskie | Zdarzenia audytu dla odrzuceń CSRF i przekroczeń limitów; na produkcji format ECS także na konsoli (`logs.consoleFormat: ecs`) lub zamiana znaków końca linii w komunikatach | mały |

**Stan:** G1, G2, G3, G4, G7, G11, G12 – **zrobione w 0.18.0** (✅), każde z testem regresji; G8 – **zrobione w 0.37.0**. Zostały: G5, G6, G9, G10 –
konfiguracja i procedury przy wdrożeniu.
Uwaga wdrożeniowa do G1: ustawić `TRUSTED_PROXIES` (adresy ingress/F5), inaczej audyt pokazuje adres ingress zamiast
klienta. G2: zmiana nazwy ciasteczka sesji wylogowuje wszystkich przy wdrożeniu 0.18.0.

Poza zakresem L2, ale warte odnotowania: eksport CSV neutralizuje formuły (CSV injection, V1.2.10 – L3); audyt jest
w bazie nienaruszalny także dla konta aplikacji; odpowiedzi 404 zamiast 403 dla obiektów spoza uprawnień.

