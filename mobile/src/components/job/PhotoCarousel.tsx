import React, { useRef, useState } from "react";
import { View, ScrollView, useWindowDimensions } from "react-native";
import { Image } from "expo-image";
import { spacing } from "@/src/theme";
import { styles } from "./styles";

export default function PhotoCarousel({ photos }: { photos: any[] }) {
  const { width } = useWindowDimensions();
  const cardWidth = Math.min(width, 600) - spacing.lg * 2;
  const [active, setActive] = useState(0);
  const ref = useRef<ScrollView>(null);

  if (!photos.length) return null;

  return (
    <View testID="photo-carousel">
      <ScrollView
        ref={ref}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={(e) => setActive(Math.round(e.nativeEvent.contentOffset.x / cardWidth))}
        scrollEventThrottle={16}
      >
        {photos.map((p: any) => (
          <View key={p.id} style={[styles.carouselSlide, { width: cardWidth }]} testID={`carousel-photo-${p.id}`}>
            <Image source={{ uri: p.data }} style={styles.carouselImg} contentFit="cover" />
          </View>
        ))}
      </ScrollView>
      {photos.length > 1 ? (
        <View style={styles.dotsRow}>
          {photos.map((p: any, i: number) => (
            <View key={p.id} style={[styles.dot, i === active && styles.dotActive]} />
          ))}
        </View>
      ) : null}
    </View>
  );
}
