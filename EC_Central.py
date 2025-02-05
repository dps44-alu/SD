import pygame

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
    def loadMap(self, file):
        try:
            with open(file, "r") as file:
                for line in file:
                    parts = line.split()    # Divide en partes ignorando espacios extra
                    if len(parts) == 3:     # Asegurar que haya una letra y dos números
                        letter = parts[0]
                        try:
                            x, y = int(parts[1]), int(parts[2])

                            # Si las coordenadas son mayores que el número de celdas, significa que ya están en píxeles
                            if x >= WIDTH or y >= HEIGHT:
                                grid_x, grid_y = x // CELL_SIZE, y // CELL_SIZE
                            else:
                                grid_x, grid_y = x, y   # Escalar de 20x20 a 800x800 multiplicando por el tamaño de celda

                            # Validar que esté dentro del rango
                            if 0 <= grid_x < COLS and 0 <= grid_y < ROWS:
                                self.grid[grid_y][grid_x] = letter

                        except ValueError:
                            print(f"Ignorando línea inválida: {line.strip()}")
                            
        except FileNotFoundError:
            print(f"Error: No se encontró el archivo '{file}'")

    # DIbuja el mapa
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

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Mapa 20x20")

    font = pygame.font.Font(None, 36)   # Fuente para las letras
    city_map = CityMap()
    city_map.loadMap("city_map.txt")    # Cargar desde el archivo

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