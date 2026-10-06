#include <DHT.h>

// --- Broches ---
#define DHT_PIN 4     // DATA du DHT11 sur D4
#define MQ2_PIN 34    // AO du MQ-2 sur D34

// --- Réglages ---
#define PRECHAUFFAGE_MS 60000   // 60 s de chauffe du MQ-2
#define SEUIL_ALERTE 1.5        // alerte si la valeur dépasse 1,5 × le niveau air propre
#define NB_LECTURES 20          // nombre de lectures pour la moyenne

DHT dht(DHT_PIN, DHT11);
int niveauAirPropre = 0;

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
}

void loop() {
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

  delay(2000);
}