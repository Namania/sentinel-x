#include <DHT.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h> // [AJOUT] pour lire le message du buzzer

// --- Broches ---
#define DHT_PIN 4   // DATA du DHT11 sur D4
#define MQ2_PIN 34  // AO du MQ-2 sur D34
#define buzzerPin 2 // Buzzer sur D2

// --- Réglages ---
#define PRECHAUFFAGE_MS 60000 // 60 s de chauffe du MQ-2
#define SEUIL_ALERTE 1.5      // alerte si la valeur dépasse 1,5 × le niveau air propre
#define NB_LECTURES 20        // nombre de lectures pour la moyenne
#define BUZZER_ACTIF false    // false = buzzer passif (il faut lui envoyer une fréquence)
#define FREQ_BUZZER 2000      // [BUZZER] fréquence du bip en Hz (essaie entre 1000 et 4000)

DHT dht(DHT_PIN, DHT11);
int niveauAirPropre = 0;

// [MQTT] Configuration et fonctions réseau

const char *WIFI_SSID = "wifi myDiL";
const char *WIFI_PASSWORD = "myDiL@2025";
const char *MQTT_HOST = "192.168.0.70";
const uint16_t MQTT_PORT = 1883;
const char *MQTT_TOPIC = "sentinel/esp1";
const char *MQTT_ALERT_TOPIC = "sentinel/cmd/buzzer"; // [CORRIGÉ] topic du contrat
int nb_alerts = 1;
bool buzzerOn = false; // [AJOUT] dernier état "on" reçu du serveur

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
unsigned long dernierEssaiMqtt = 0;

// [MQTT] Connexion Wi-Fi avec délai max : sans réseau, les capteurs tournent quand même
void connectWifi()
{
  Serial.print("Connexion au Wi-Fi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long debut = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - debut < 10000)
  {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.print("\nConnecté ! IP de l'ESP : ");
    Serial.println(WiFi.localIP());
  }
  else
  {
    Serial.println("\nWi-Fi indisponible, on continue sans (reconnexion auto en fond)");
  }
}

// [MQTT] Souscrit aux alertes, pour recevoir les messages du broker
void subscribeAlerts(const char *topic)
{
  if (!mqtt.connected())
    return;
  if (!mqtt.subscribe(topic, 1))
  {
    Serial.println(" [MQTT] échec de souscription aux alertes");
  }
  else
  {
    Serial.println(" [MQTT] souscrit aux alertes");
  }
}

// [MQTT] Maintient la connexion au broker sans jamais bloquer les mesures
void maintenirMqtt()
{
  if (mqtt.connected())
  {
    mqtt.loop();
    return;
  }
  if (WiFi.status() != WL_CONNECTED)
    return;
  if (dernierEssaiMqtt != 0 && millis() - dernierEssaiMqtt < 5000)
    return; // 1 essai / 5 s

  dernierEssaiMqtt = millis();
  String clientId = "espInterieur-" + WiFi.macAddress();
  clientId.replace(":", "");
  Serial.print("Connexion au broker... ");
  if (mqtt.connect(clientId.c_str()))
  {
    Serial.println("OK");
    subscribeAlerts(MQTT_ALERT_TOPIC); // s'abonner à chaque connexion
  }
  else
  {
    Serial.print("échec, rc=");
    Serial.println(mqtt.state()); // -2 = injoignable, 5 = non autorisé
  }
}

// [MQTT] Publie les mesures en JSON
void publierMesures(float temperature, float humidite, int gaz)
{
  if (!mqtt.connected())
    return;

  const char *etat;
  if (millis() < PRECHAUFFAGE_MS)
  {
    etat = "prechauffage";
  }
  else if (gaz > niveauAirPropre * SEUIL_ALERTE)
  {
    etat = "alerte";
  }
  else
  {
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

  if (!mqtt.publish(MQTT_TOPIC, payload.c_str()))
  {
    Serial.println(" [MQTT] échec de publication");
  }
}

// [AJOUT] Appelée automatiquement quand un message arrive sur le topic du buzzer
void recevoirAlerte(char *topic, byte *payload, unsigned int length)
{
  JsonDocument doc;
  if (deserializeJson(doc, payload, length))
    return; // JSON invalide : on ignore

  buzzerOn = doc["on"];
  nb_alerts = doc["open"] | 1;
  if (nb_alerts < 1)
    nb_alerts = 1; // évite une division par zéro

  Serial.printf(" [MQTT] buzzer %s, %d alerte(s)\n", buzzerOn ? "ON" : "OFF", nb_alerts);
}

// [BUZZER] Allume ou éteint le buzzer, qu'il soit actif ou passif
// - actif : un simple HIGH suffit, il a son propre oscillateur
// - passif : il faut lui envoyer un signal carré à une fréquence audible
void buzzer(bool on)
{
  if (BUZZER_ACTIF)
  {
    digitalWrite(buzzerPin, on ? HIGH : LOW);
  }
  else
  {
    if (on)
      tone(buzzerPin, FREQ_BUZZER);
    else
      noTone(buzzerPin);
  }
}

// [AJOUT] Remplace le delay(2000) : attend en faisant biper le buzzer si besoin
// Plus il y a d'alertes, plus ça bipe vite
void attendreEtBiper(unsigned long duree)
{
  unsigned long debut = millis();
  while (millis() - debut < duree)
  {
    mqtt.loop(); // pour recevoir un "on": false sans attendre
    if (buzzerOn)
    {
      buzzer(true); // [BUZZER] remplace digitalWrite(HIGH)
      delay(500 / nb_alerts);
      buzzer(false); // [BUZZER] remplace digitalWrite(LOW)
      delay(500 / nb_alerts);
    }
    else
    {
      buzzer(false); // [BUZZER]
      delay(50);
    }
  }
}

// Lit le MQ-2 plusieurs fois et renvoie la moyenne en mV
int lireGaz()
{
  long somme = 0;
  for (int i = 0; i < NB_LECTURES; i++)
  {
    somme += analogReadMilliVolts(MQ2_PIN);
    delay(5);
  }
  return somme / NB_LECTURES;
}

void setup()
{
  Serial.begin(115200);
  pinMode(buzzerPin, OUTPUT);
  buzzer(false); // [BUZZER] s'assure qu'il est muet au démarrage
  dht.begin();
  analogSetPinAttenuation(MQ2_PIN, ADC_11db); // plage de mesure 0 – 3,3 V
  Serial.println("Préchauffage du MQ-2 pendant 60 secondes...");

  // [MQTT]
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(recevoirAlerte);
}

void loop()
{
  maintenirMqtt(); // [MQTT]

  // --- DHT11 ---
  float temperature = dht.readTemperature();
  float humidite = dht.readHumidity();

  // --- MQ-2 ---
  int gaz = lireGaz();

  // --- Affichage ---
  if (isnan(temperature) || isnan(humidite))
  {
    Serial.print("Température : erreur ");
  }
  else
  {
    Serial.printf("Température : %.1f °C Humidité : %.0f %%", temperature, humidite);
  }
  Serial.printf(" | Gaz : %4d mV", gaz);

  if (millis() < PRECHAUFFAGE_MS)
  {
    Serial.println(" (préchauffage...)");
  }
  else
  {
    // Le premier relevé après la chauffe sert de niveau « air propre »
    if (niveauAirPropre == 0)
    {
      niveauAirPropre = gaz;
      Serial.printf(" -> niveau air propre enregistré : %d mV\n", niveauAirPropre);
    }
    else if (gaz > niveauAirPropre * SEUIL_ALERTE)
    {
      Serial.println(" ⚠️ ALERTE GAZ / FUMÉE !");
    }
    else
    {
      Serial.println(" OK");
    }
  }

  publierMesures(temperature, humidite, gaz); // [MQTT]

  attendreEtBiper(2000);
}