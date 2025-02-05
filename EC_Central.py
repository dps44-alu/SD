import pygame
import socket

# Constantes CityMap
WIDTH, HEIGHT = 800, 800
ROWS, COLS = 20, 20
CELL_SIZE = WIDTH // COLS

# Colores CityMap
WHITE = (255, 255, 255)
GRAY = (200, 200, 200)
BLACK = (0, 0, 0)
BLUE = (102, 168, 207)

class CityMap:
    def __init__(self):
        self.grid = [["" for _ in range(COLS)] for _ in range(ROWS)]  # Mapa vacío

    # Carga las letras del mapa
    def loadMap(self, file, sites):
        try:
            with open(file, "r") as file:
                for line in file:
                    parts = line.split()    # Divide en partes ignorando espacios extra
                    if len(parts) == 3:     # Asegurar que haya una letra y dos números
                        letter = parts[0]
                        try:
                            x, y = int(parts[1]), int(parts[2]) 

                            # Validar que esté dentro del rango
                            if 0 <= x < COLS and 0 <= y < ROWS:
                                self.grid[y][x] = letter
                                sites[letter] = (x, y)

                        except ValueError:
                            print(f"Ignorando línea inválida: {line.strip()}")
                            
        except FileNotFoundError:
            print(f"Error: No se encontró el archivo '{file}'")

    # Dibuja el mapa
    def draw(self, screen, font):
        for row in range(ROWS):
            for col in range(COLS):
                rect = pygame.Rect(col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE)

                # Dibujar letra si hay una en la celda
                if self.grid[row][col]:
                    pygame.draw.rect(screen, BLUE, rect)        # Relleno
                    text = font.render(self.grid[row][col], True, BLACK)
                    screen.blit(text, (col * CELL_SIZE + CELL_SIZE // 3, row * CELL_SIZE + CELL_SIZE // 4))
                else:
                    pygame.draw.rect(screen, GRAY, rect)        # Relleno

                pygame.draw.rect(screen, BLACK, rect, 1)    # Borde


class Central:
    def __init__(self, port):
        self.ip = socket.gethostbyname(socket.gethostname())
        self.port = port


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Mapa 20x20")

    font = pygame.font.Font(None, 36)   # Fuente para las letras
    sites = {}                          # Localizaciones del mapa

    city_map = CityMap()
    city_map.loadMap("city_map.txt", sites)     # Cargar desde el archivo

    running = True
    while running:
        screen.fill(WHITE)
        city_map.draw(screen, font)
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        pygame.display.flip()

    pygame.quit()

if __name__ == "__main__":
    main()