# Alerta Next – konsola alertów dla zespołów IT

*Materiał dla kadry kierowniczej: czym jest aplikacja, co robi i co dzięki niej zyskujemy.*

---

## W skrócie

**Alerta Next to jedno miejsce, w którym zespoły IT widzą wszystkie problemy swoich systemów, reagują na nie
i rozliczają się z reakcji.** Zbiera alerty z systemów monitorowania, przypisuje je do właściwych środowisk i zespołów,
odsiewa szum, powiadamia właściwe osoby i zostawia pełny, nienaruszalny ślad tego, kto i kiedy co zrobił.

Aplikacja zastępuje wcześniej używane narzędzie, które przestało być rozwijane, miało nieczytelny model uprawnień
i znane problemy bezpieczeństwa. Jest wdrożona i przechodzi testy akceptacyjne użytkowników.

---

## Jaki problem rozwiązujemy

| Dziś (bez spójnej konsoli) | Skutek dla organizacji |
|---|---|
| Alerty rozproszone po wielu narzędziach i skrzynkach | Problemy wykrywane późno albo przez klientów |
| Dużo „szumu” – alertów, które znikają same albo nikogo nie dotyczą | Zmęczenie alertami, ważne sygnały giną w tłumie |
| Niejasne, kto odpowiada za dany alert | Nikt nie reaguje albo reaguje kilka osób naraz |
| Brak twardych danych o czasie reakcji | Trudno ocenić jakość obsługi i planować zasoby |
| Słaby ślad audytowy | Trudno wykazać przed audytem, kto i kiedy podjął działanie |
| Przestarzałe narzędzie bez wsparcia | Rosnące ryzyko bezpieczeństwa i koszt utrzymania |

---

## Co zyskujemy

| Korzyść | Skąd się bierze | Jak to zmierzyć |
|---|---|---|
| **Szybsza reakcja na awarie** | Wszystkie alerty w jednym widoku na żywo, od razu przypisane do środowiska i zespołu; powiadomienia do właściwych osób | Średni czas do potwierdzenia (MTTA) i do rozwiązania (MTTR) – liczone automatycznie |
| **Mniej szumu, więcej uwagi na tym, co ważne** | Wykrywanie alertów niestabilnych, okna serwisowe, raport „czy alert wymaga działania” z gotowymi podpowiedziami dla autorów reguł | Udział alertów, które znikają same lub są zamykane bez komentarza – powinien maleć |
| **Jasna odpowiedzialność** | Uprawnienia per środowisko: każdy widzi i obsługuje tylko swoje systemy; alert bez właściciela trafia do kwarantanny, zamiast ginąć | Liczba alertów w kwarantannie; czas potwierdzenia per zespół |
| **Szybsza diagnoza przyczyny** | Oś czasu łącząca alerty z wdrożeniami zmian; jednym kliknięciem przejście do wykresów i logów dla danego alertu | Czas od alertu do wskazania przyczyny (np. konkretnego wdrożenia) |
| **Gotowość na audyt i kontrolę** | Każda akcja na alercie i każda zmiana uprawnień w dzienniku audytu chronionym kryptograficznie przed zmianą; okresowy przegląd dostępu z eksportem | Czas przygotowania materiału dla audytu; brak uwag dotyczących rozliczalności |
| **Niższe ryzyko bezpieczeństwa** | Aplikacja napisana od nowa według uznanego standardu bezpieczeństwa aplikacji (OWASP ASVS, poziom 2), z automatycznym skanowaniem podatności przy każdej zmianie | Wyniki skanów i testów bezpieczeństwa |
| **Brak kosztów licencyjnych** | Własna aplikacja na sprawdzonych, otwartych technologiach; działa we własnej infrastrukturze | Koszt licencji = 0; koszt utrzymania = czas zespołu |
| **Niezależność od dostawcy** | Pełna kontrola nad kodem, danymi i planem rozwoju | Funkcje dodawane wtedy, gdy są potrzebne – bez czekania na producenta |

---

## Najważniejsze funkcje

### Codzienna praca zespołów
- **Konsola na żywo** – lista aktywnych alertów odświeżana natychmiast, z filtrami (środowisko, ważność, usługa,
  dowolne etykiety) i zapisanymi widokami wspólnymi dla zespołu.
- **Akcje na alertach** – potwierdzenie („zajmuję się tym”), notatki, zamknięcie, wyciszenie, również dla wielu
  alertów naraz. Potwierdzenie wygasa po ustalonym czasie, więc żaden alert nie „wisi” zapomniany.
- **Panel szczegółów** – opis, instrukcja postępowania, historia wystąpień, kto i kiedy reagował.
- **Widok ścienny (kiosk)** dla sal operacyjnych oraz **panel wskaźników** z bieżącą sytuacją.
- Interfejs po polsku i angielsku, tryb jasny i ciemny.

### Mniej szumu
- **Wykrywanie alertów niestabilnych** – alert, który co chwilę wraca, jest oznaczany zamiast zalewać konsolę.
- **Okna serwisowe** – planowane prace wyciszają alerty danego środowiska na czas prac, z pełną ewidencją.
- **Porządki w wyciszeniach** – widać wyciszenia, które nic już nie wyciszają, trwają zbyt długo lub założono je
  poza aplikacją; ostrzeżenie, gdy wyciszenie zaraz się skończy.
- **Raport „czy alert wymaga działania”** – wskazuje reguły generujące szum i podpowiada, co w nich poprawić.

### Odpowiedzialność i uprawnienia
- **Środowiska** – alerty są automatycznie przypisywane do środowisk na podstawie ich etykiet; alert, którego nie da
  się przypisać, trafia do kwarantanny i jest widoczny dla administratorów.
- **Prosty model uprawnień**: grupa × rola × środowiska. Gotowe role (m.in. operator, opiekun, audytor,
  administrator dostępu); odebranie uprawnień działa natychmiast.
- **Logowanie firmowym kontem (SSO)** z przenoszeniem grup; konta lokalne tylko awaryjnie.
- **Przegląd dostępu** – kto ma jakie uprawnienia i skąd, z eksportem do okresowej recertyfikacji; nieużywane konta
  lokalne mogą wyłączać się automatycznie.
- **Tester etykiet** – administrator sprawdza przed uruchomieniem nowej reguły monitorowania, dokąd trafi alert,
  co go wyciszy i kto dostanie powiadomienie.

### Powiadomienia
- **Powiadomienia e-mail według reguł** (środowisko, ważność, etykiety → grupy), z przypomnieniami, dopóki nikt
  nie potwierdzi alertu.
- **Godziny pracy** grup i osób – w godzinach dyżuru wystarcza konsola, poza nimi idzie mail; alerty krytyczne
  domyślnie zawsze.
- **Codzienny raport e-mail** z podsumowaniem minionej doby.
- Poczta wychodzi wyłącznie do dozwolonych domen, a każdy mail jest odnotowany w dzienniku audytu.

### Wnioski i raporty
- **Czas reakcji** (MTTA, MTTR) per środowisko lub zespół, najczęstsze i najdłuższe alerty, alerty niestabilne.
- **Oś czasu** – historia alertów na osi czasu z akcjami ludzi, oknami serwisowymi i **wdrożeniami zmian**;
  gotowa do wklejenia w raport poawaryjny (eksport do obrazu).
- Eksport danych do CSV.

### Kontekst do szybkiej diagnozy
- **Wdrożenia zmian** z systemu wdrożeniowego widoczne obok alertów: „co zmieniono w tym środowisku tuż przed
  awarią”.
- **Linki do narzędzi** (wykresy, logi) budowane automatycznie dla każdego alertu – od razu na właściwym okresie.

### Bezpieczeństwo i zgodność
- Projekt według **OWASP ASVS, poziom 2** – standardu dla aplikacji przetwarzających dane wymagające ochrony.
- **Dziennik audytu nie do zmiany po cichu**: zapisy chronione łańcuchem skrótów kryptograficznych, codziennie
  sprawdzanym; próba zmiany lub usunięcia wpisu – także bezpośrednio w bazie danych – zostanie wykryta i zgłoszona.
- Sesje zarządzane po stronie serwera, ponowne uwierzytelnienie przy operacjach wrażliwych, podgląd i kończenie
  własnych sesji.
- Automatyczne skanowanie podatności obrazów przy każdej zmianie, zestawienie komponentów (SBOM) przy każdym wydaniu.
- Integracje z innymi systemami tylko przez klucze ograniczone do wskazanych środowisk.

### Niezawodność i utrzymanie
- Działa w kilku kopiach jednocześnie – awaria jednej nie przerywa pracy.
- Aplikacja sama jest monitorowana: zgłasza opóźnienia w dostarczaniu alertów, problemy z zadaniami w tle
  i naruszenie dziennika audytu.
- Udokumentowana procedura kopii zapasowych i odtwarzania; próba odtworzenia jest warunkiem wersji 1.0.
- Nowe wersje wydawane automatycznie, z opisem zmian „Co nowego” widocznym w aplikacji.

---

## Jak to działa (w uproszczeniu)

```
 Systemy monitorowania ──┐
 Inne źródła alertów ────┼──►  Alerta Next  ──►  konsola zespołów, widok ścienny, raporty
 System wdrożeń zmian ───┘         │
                                   ├──►  powiadomienia e-mail do właściwych osób
                                   └──►  dziennik audytu (chroniony) i metryki dla monitoringu
```

Alerty są **wysyłane** do aplikacji przez systemy źródłowe – Alerta Next nie łączy się z monitorowanymi systemami
i nie wymaga do nich dostępu.

---

## Koszty i ryzyka

| Obszar | Ocena |
|---|---|
| Licencje | Brak – własna aplikacja na otwartych technologiach |
| Infrastruktura | Niewielka: działa w istniejącym środowisku kontenerowym obok innych usług |
| Utrzymanie | Czas zespołu; ułatwione przez automatyczne testy, skanowanie i wydania |
| Ryzyko „wiedzy w jednej głowie” | Ograniczane dokumentacją techniczną, instrukcją wdrożenia, procedurami operacyjnymi i standardowym stosem technologicznym |
| Ryzyko wdrożenia | Ograniczone: pilotaż i testy akceptacyjne użytkowników przed pełnym przejściem |

---

## Stan i dalsze kroki

1. **Teraz:** aplikacja wdrożona, trwają testy akceptacyjne użytkowników.
2. **Wersja 1.0:** po zakończeniu testów – zamknięcie zgłoszonych uwag, potwierdzona procedura odtwarzania, przegląd
   konfiguracji.
3. **Kolejny etap (plan):** obsługa incydentów – grupowanie powiązanych alertów w jeden incydent z osobą
   prowadzącą, komunikacją i podsumowaniem poawaryjnym; następnie integracja z systemem zgłoszeń.

---

## Jak ocenimy sukces

- **MTTA i MTTR** spadają w kolejnych miesiącach (dane z raportów aplikacji).
- **Udział szumu** (alerty znikające same, zamykane bez komentarza) maleje dzięki poprawkom reguł.
- **Kwarantanna** jest pusta lub bliska zeru – każdy alert ma właściciela.
- **Audyt i przegląd dostępu** przygotowywane z aplikacji, bez ręcznego zbierania danych.
- **Zespoły korzystają z konsoli na co dzień** zamiast z rozproszonych skrzynek i narzędzi.
