#include <DHT.h>
#include <WiFi.h>          
#include <PubSubClient.h>   

// --- Broches ---
#define DHT_PIN 4     // DATA du DHT11 sur D4
#define MQ2_PIN 34    // AO du MQ-2 sur D34

// --- Réglages ---
#define PRECHAUFFAGE_MS 60000   // 60 s de chauffe du MQ-2
#define SEUIL_ALERTE 1.5        // alerte si la valeur dépasse 1,5 × le niveau air propre
#define NB_LECTURES 20          // nombre de lectures pour la moyenne

DHT dht(DHT_PIN, DHT11);
int niveauAirPropre = 0;

// [MQTT] Configuration et fonctions réseau

const char* WIFI_SSID     = "wifi myDiL";
const char* WIFI_PASSWORD = "myDiL@2025";
const char* MQTT_HOST     = "192.168.0.70";
const uint16_t MQTT_PORT  = 1883;
const char* MQTT_TOPIC    = "sentinel/esp1";

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
unsigned long dernierEssaiMqtt = 0;

// [MQTT] Connexion Wi-Fi avec délai max : sans réseau, les capteurs tournent quand même
void connectWifi() {
  Serial.print("Connexion au Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long debut = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - debut < 10000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\nConnecté ! IP de l'ESP : ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWi-Fi indisponible, on continue sans (reconnexion auto en fond)");
  }
}

// [MQTT] Maintient la connexion au broker sans jamais bloquer les mesures
void maintenirMqtt() {
  if (mqtt.connected()) {
    mqtt.loop();
    return;
  }
  if (WiFi.status() != WL_CONNECTED) return;
  if (dernierEssaiMqtt != 0 && millis() - dernierEssaiMqtt < 5000) return;  // 1 essai / 5 s

  dernierEssaiMqtt = millis();
  String clientId = "espInterieur-" + WiFi.macAddress();
  clientId.replace(":", "");
  Serial.print("Connexion au broker... ");
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("OK");
  } else {
    Serial.print("échec, rc=");
    Serial.println(mqtt.state());   // -2 = injoignable, 5 = non autorisé
  }
}

// [MQTT] Publie les mesures en JSON, en relisant l'état sans toucher à la logique d'origine
void publierMesures(float temperature, float humidite, int gaz) {
  if (!mqtt.connected()) return;

  const char* etat;
  if (millis() < PRECHAUFFAGE_MS) {
    etat = "prechauffage";
  } else if (gaz > niveauAirPropre * SEUIL_ALERTE) {
    etat = "alerte";
  } else {
    etat = "ok";
  }

  String payload = "{\"temperature\":";
  payload += isnan(temperature) ? String("null") : String(temperature, 1);
  payload += ",\"humidite\":";
  payload += isnan(humidite) ? String("null") : String(humidite, 0);
  payload += ",\"gaz_mv\":";
  payload += String(gaz);
  payload += ",\"etat_gaz\":\"";
  payload += etat;
  payload += "\"}";

  if (!mqtt.publish(MQTT_TOPIC, payload.c_str())) {
    Serial.println("  [MQTT] échec de publication");
  }
}

// Lit le MQ-2 plusieurs fois et renvoie la moyenne en mV
int lireGaz() {
  long somme = 0;
  for (int i = 0; i < NB_LECTURES; i++) {
    somme += analogReadMilliVolts(MQ2_PIN);
    delay(5);
  }
  return somme / NB_LECTURES;
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  analogSetPinAttenuation(MQ2_PIN, ADC_11db);  // plage de mesure 0 – 3,3 V
  Serial.println("Préchauffage du MQ-2 pendant 60 secondes...");

  // [MQTT]
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  maintenirMqtt();   // [MQTT]

  // --- DHT11 ---
  float temperature = dht.readTemperature();
  float humidite = dht.readHumidity();

  // --- MQ-2 ---
  int gaz = lireGaz();

  // --- Affichage ---
  if (isnan(temperature) || isnan(humidite)) {
    Serial.print("Température : erreur                       ");
  } else {
    Serial.printf("Température : %.1f °C  Humidité : %.0f %%", temperature, humidite);
  }
  Serial.printf("  |  Gaz : %4d mV", gaz);

  if (millis() < PRECHAUFFAGE_MS) {
    Serial.println("  (préchauffage...)");
  } else {
    // Le premier relevé après la chauffe sert de niveau « air propre »
    if (niveauAirPropre == 0) {
      niveauAirPropre = gaz;
      Serial.printf("  -> niveau air propre enregistré : %d mV\n", niveauAirPropre);
    } else if (gaz > niveauAirPropre * SEUIL_ALERTE) {
      Serial.println("  ⚠️  ALERTE GAZ / FUMÉE !");
    } else {
      Serial.println("  OK");
    }
  }

  publierMesures(temperature, humidite, gaz);   // [MQTT]

  delay(2000);
}